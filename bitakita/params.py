"""BitAkita constants and network parameters."""

# --- Economics (Bitcoin-style) ---
INITIAL_REWARD = 50_0000_0000       # 50 BITA in inu (satoshi equivalent)
HALVING_INTERVAL = 210_000          # Blocks between reward halvings
MAX_SUPPLY = 21_000_000 * 100_000_000  # 21 million BITA

# --- Block Timing ---
TARGET_BLOCK_TIME = 60              # 60 seconds (vs Bitcoin's 600)
DIFFICULTY_ADJUSTMENT_INTERVAL = 360  # ~6 hours (vs Bitcoin's ~2 weeks)

# --- Dynamic Block Size ---
MIN_BLOCK_SIZE = 500_000            # 500 KB minimum
MAX_BLOCK_SIZE = 8_000_000          # 8 MB maximum
TARGET_BLOCK_SIZE = 2_000_000       # 2 MB target
BLOCK_SIZE_ADJUSTMENT_FACTOR = 1024 # Denominator for size adjustment

# --- EIP-1559 Fee Mechanism ---
INITIAL_BASE_FEE = 1000             # Initial base fee in inu
MIN_BASE_FEE = 100                  # Minimum base fee
BASE_FEE_MAX_CHANGE_DENOMINATOR = 8 # Max 12.5% change per block
FEE_BURN_PERCENTAGE = 50            # 50% of base fee is burned

# --- PoS Parameters ---
MIN_STAKE_AMOUNT = 1000_0000_0000   # 1000 BITA to become a validator
STAKE_LOCK_PERIOD = 1000            # Blocks before stake can be withdrawn
CHECKPOINT_INTERVAL = 10            # PoS checkpoint every 10 blocks
CHECKPOINT_QUORUM = 67              # 67% of stake must agree for finality
SLASH_PERCENTAGE = 10               # 10% slashing for misbehavior
ANNUAL_STAKE_REWARD_RATE = 5        # 5% annual return on staked BITA

# --- Governance ---
GOVERNANCE_VOTING_PERIOD = 10_000   # Blocks for a governance vote
GOVERNANCE_QUORUM = 50              # 50% of staked BITA must vote
GOVERNANCE_APPROVAL_THRESHOLD = 66  # 66% approval needed

# --- UTXO Rental ---
UTXO_RENT_GRACE_PERIOD = 100_000    # Blocks before rent starts (~70 days)
UTXO_RENT_PER_BLOCK = 1             # 1 inu per block per UTXO after grace
UTXO_DUST_THRESHOLD = 546           # UTXOs below this are prunable

# --- Network ---
DEFAULT_INITIAL_BITS = 0x2000FFFF   # Easy initial difficulty for testing
MAX_BLOCK_WEIGHT = 4_000_000        # Weight limit

# --- Address Versions ---
MAINNET_P2PKH = b"\x17"             # 'A' prefix for BitAkita mainnet
TESTNET_P2PKH = b"\x41"             # 't' prefix for testnet
STEALTH_VERSION = b"\x2a"           # 'S' prefix for stealth addresses
