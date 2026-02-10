"""
On-chain Governance for BitAkita.

Bitcoin has no formal governance mechanism. Protocol changes require
off-chain social consensus and contentious hard/soft forks.

BitAkita's on-chain governance allows stakeholders to:
1. Propose parameter changes (block size, fees, etc.)
2. Vote with stake-weighted voting power
3. Automatically apply approved changes after voting period

Proposal lifecycle:
1. PROPOSED: A validator creates a proposal
2. VOTING: Validators cast votes during the voting period
3. APPROVED/REJECTED: Based on quorum and approval threshold
4. EXECUTED: Approved proposals are automatically applied

Governable parameters:
- TARGET_BLOCK_SIZE: Target block size
- MAX_BLOCK_SIZE: Maximum block size
- BASE_FEE_MAX_CHANGE_DENOMINATOR: Fee volatility
- CHECKPOINT_INTERVAL: Checkpoint frequency
- MIN_STAKE_AMOUNT: Minimum stake requirement
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitakita import params
from bitakita.consensus.pos import StakePool


class ProposalType(Enum):
    """Types of governance proposals."""
    PARAM_CHANGE = auto()     # Change a network parameter
    EMERGENCY_ACTION = auto() # Emergency protocol action


class ProposalStatus(Enum):
    """Lifecycle status of a proposal."""
    PROPOSED = auto()
    VOTING = auto()
    APPROVED = auto()
    REJECTED = auto()
    EXECUTED = auto()


# Parameters that can be changed via governance
GOVERNABLE_PARAMS = {
    "TARGET_BLOCK_SIZE": (500_000, 32_000_000),   # min, max bounds
    "MAX_BLOCK_SIZE": (1_000_000, 64_000_000),
    "BASE_FEE_MAX_CHANGE_DENOMINATOR": (2, 32),
    "CHECKPOINT_INTERVAL": (5, 100),
    "MIN_STAKE_AMOUNT": (100_0000_0000, 10000_0000_0000),
    "UTXO_RENT_GRACE_PERIOD": (10_000, 1_000_000),
    "FEE_BURN_PERCENTAGE": (0, 100),
}


@dataclass
class Vote:
    """A validator's vote on a proposal."""
    validator_pubkey_hash: bytes
    stake_weight: int
    approve: bool


@dataclass
class Proposal:
    """A governance proposal."""
    proposal_id: bytes          # Hash of proposal content
    proposer_pubkey_hash: bytes
    proposal_type: ProposalType
    param_name: str             # Parameter to change
    new_value: int              # Proposed new value
    start_height: int           # Block height when voting starts
    end_height: int             # Block height when voting ends
    status: ProposalStatus = ProposalStatus.PROPOSED
    votes: list[Vote] = field(default_factory=list)

    # Computed during voting
    total_approve_stake: int = 0
    total_reject_stake: int = 0
    total_voted_stake: int = 0

    @property
    def approval_percentage(self) -> float:
        if self.total_voted_stake == 0:
            return 0.0
        return (self.total_approve_stake / self.total_voted_stake) * 100

    @property
    def participation_percentage(self) -> float:
        """Placeholder - requires total stake context."""
        return 0.0


class GovernanceSystem:
    """
    On-chain governance system for BitAkita.
    """

    def __init__(self, stake_pool: StakePool):
        self.stake_pool = stake_pool
        self.proposals: dict[bytes, Proposal] = {}
        self.executed_changes: list[tuple[str, int, int]] = []  # (param, old, new)
        # Runtime-adjustable parameters (start with defaults from params module)
        self.active_params: dict[str, int] = {
            "TARGET_BLOCK_SIZE": params.TARGET_BLOCK_SIZE,
            "MAX_BLOCK_SIZE": params.MAX_BLOCK_SIZE,
            "BASE_FEE_MAX_CHANGE_DENOMINATOR": params.BASE_FEE_MAX_CHANGE_DENOMINATOR,
            "CHECKPOINT_INTERVAL": params.CHECKPOINT_INTERVAL,
            "MIN_STAKE_AMOUNT": params.MIN_STAKE_AMOUNT,
            "UTXO_RENT_GRACE_PERIOD": params.UTXO_RENT_GRACE_PERIOD,
            "FEE_BURN_PERCENTAGE": params.FEE_BURN_PERCENTAGE,
        }

    def create_proposal(
        self,
        proposer_pubkey_hash: bytes,
        param_name: str,
        new_value: int,
        current_height: int,
    ) -> tuple[bool, str, Optional[Proposal]]:
        """
        Create a new governance proposal.

        Only active validators can propose.
        """
        # Verify proposer is an active validator
        if proposer_pubkey_hash not in self.stake_pool.validators:
            return False, "Only validators can create proposals", None

        validator = self.stake_pool.validators[proposer_pubkey_hash]
        if not validator.is_active or validator.slashed:
            return False, "Validator is not active", None

        # Validate parameter
        if param_name not in GOVERNABLE_PARAMS:
            return False, f"Parameter '{param_name}' is not governable", None

        min_val, max_val = GOVERNABLE_PARAMS[param_name]
        if not (min_val <= new_value <= max_val):
            return False, f"Value must be between {min_val} and {max_val}", None

        # Generate proposal ID
        content = (
            param_name.encode()
            + new_value.to_bytes(8, "big")
            + current_height.to_bytes(8, "big")
        )
        proposal_id = double_sha256(content)

        proposal = Proposal(
            proposal_id=proposal_id,
            proposer_pubkey_hash=proposer_pubkey_hash,
            proposal_type=ProposalType.PARAM_CHANGE,
            param_name=param_name,
            new_value=new_value,
            start_height=current_height,
            end_height=current_height + params.GOVERNANCE_VOTING_PERIOD,
            status=ProposalStatus.VOTING,
        )

        self.proposals[proposal_id] = proposal
        return True, "Proposal created", proposal

    def cast_vote(
        self,
        proposal_id: bytes,
        voter_pubkey_hash: bytes,
        approve: bool,
    ) -> tuple[bool, str]:
        """
        Cast a vote on a proposal.

        Vote weight equals the validator's stake.
        """
        if proposal_id not in self.proposals:
            return False, "Proposal not found"

        proposal = self.proposals[proposal_id]

        if proposal.status != ProposalStatus.VOTING:
            return False, f"Proposal is {proposal.status.name}, not accepting votes"

        # Verify voter is active validator
        if voter_pubkey_hash not in self.stake_pool.validators:
            return False, "Only validators can vote"

        validator = self.stake_pool.validators[voter_pubkey_hash]
        if not validator.is_active or validator.slashed:
            return False, "Validator is not active"

        # Check for duplicate votes
        for vote in proposal.votes:
            if vote.validator_pubkey_hash == voter_pubkey_hash:
                return False, "Already voted"

        vote = Vote(
            validator_pubkey_hash=voter_pubkey_hash,
            stake_weight=validator.stake_amount,
            approve=approve,
        )
        proposal.votes.append(vote)
        proposal.total_voted_stake += validator.stake_amount
        if approve:
            proposal.total_approve_stake += validator.stake_amount
        else:
            proposal.total_reject_stake += validator.stake_amount

        return True, "Vote recorded"

    def process_proposals(self, current_height: int) -> list[tuple[str, int, int]]:
        """
        Process proposals that have reached their voting deadline.

        Returns list of (param_name, old_value, new_value) for approved changes.
        """
        changes = []

        for proposal in list(self.proposals.values()):
            if proposal.status != ProposalStatus.VOTING:
                continue

            if current_height < proposal.end_height:
                continue

            # Voting period ended - tally results
            total_stake = self.stake_pool.total_stake
            participation = (
                (proposal.total_voted_stake / total_stake * 100)
                if total_stake > 0
                else 0
            )

            if participation < params.GOVERNANCE_QUORUM:
                proposal.status = ProposalStatus.REJECTED
                continue

            if proposal.approval_percentage >= params.GOVERNANCE_APPROVAL_THRESHOLD:
                proposal.status = ProposalStatus.APPROVED
                old_value = self.active_params.get(proposal.param_name, 0)
                self.active_params[proposal.param_name] = proposal.new_value
                proposal.status = ProposalStatus.EXECUTED
                change = (proposal.param_name, old_value, proposal.new_value)
                self.executed_changes.append(change)
                changes.append(change)
            else:
                proposal.status = ProposalStatus.REJECTED

        return changes

    def get_param(self, name: str) -> int:
        """Get the current value of a governable parameter."""
        return self.active_params.get(name, 0)
