# Model Configuration Settings
# This file contains all AI model configurations and can be safely committed to git

# --- Main Game Logic Models (used in main.py) ---
OPENAI_FALLBACK_MODEL = "gpt-6-luna"

DM_MAIN_MODEL = OPENAI_FALLBACK_MODEL
DM_SUMMARIZATION_MODEL = OPENAI_FALLBACK_MODEL
DM_VALIDATION_MODEL = OPENAI_FALLBACK_MODEL

# --- Action Prediction Model (used in action_predictor.py) ---
ACTION_PREDICTION_MODEL = OPENAI_FALLBACK_MODEL  # Use full model for accurate action prediction

# --- Combat Simulation Models (used in combat_manager.py) ---
COMBAT_MAIN_MODEL = OPENAI_FALLBACK_MODEL
# COMBAT_SCHEMA_UPDATER_MODEL - This was defined but not directly used.
# If needed for update_player_info, update_npc_info, update_encounter called from combat_sim,
# those modules will use their own specific models defined below.
COMBAT_DIALOGUE_SUMMARY_MODEL = OPENAI_FALLBACK_MODEL

# --- Utility and Builder Models ---
NPC_BUILDER_MODEL = OPENAI_FALLBACK_MODEL                # Used in npc_builder.py
ADVENTURE_SUMMARY_MODEL = OPENAI_FALLBACK_MODEL
CHARACTER_VALIDATOR_MODEL = OPENAI_FALLBACK_MODEL    # Used in adv_summary.py
PLOT_UPDATE_MODEL = OPENAI_FALLBACK_MODEL          # Used in plot_update.py
PLAYER_INFO_UPDATE_MODEL = OPENAI_FALLBACK_MODEL   # Used in update_player_info.py
NPC_INFO_UPDATE_MODEL = OPENAI_FALLBACK_MODEL      # Used in update_npc_info.py
MONSTER_BUILDER_MODEL = OPENAI_FALLBACK_MODEL
ENCOUNTER_UPDATE_MODEL = OPENAI_FALLBACK_MODEL
LEVEL_UP_MODEL = OPENAI_FALLBACK_MODEL                  # Used in level_up.py

# --- Transition Validation Model ---
TRANSITION_VALIDATOR_MODEL = OPENAI_FALLBACK_MODEL  # Used in transition_validator.py
TRANSITION_VALIDATOR_TEMPERATURE = 0.3                   # Low temp for analytical reasoning

# --- Token Optimization Models ---
DM_MINI_MODEL = OPENAI_FALLBACK_MODEL              # Used for simple conversations and plot-only updates
DM_FULL_MODEL = OPENAI_FALLBACK_MODEL                   # Used for complex actions requiring JSON operations

# --- Model Routing Settings ---
ENABLE_INTELLIGENT_ROUTING = True                        # Enable/disable action-based model routing
MAX_VALIDATION_RETRIES = 1                              # Retry with full model after this many validation failures

# Client-level timeout policy is owned by utils.ai_client_factory; callers must
# not add parallel per-call timeout arguments.
API_TIMEOUT_SECONDS = 120                               # Total client request timeout
API_CONNECT_TIMEOUT_SECONDS = 10                         # Client connection timeout

# --- GPT-5 Model Configuration ---
GPT5_MINI_MODEL = OPENAI_FALLBACK_MODEL              # Preferred direct-OpenAI model kept for compatibility
GPT5_FULL_MODEL = OPENAI_FALLBACK_MODEL                   # Preferred direct-OpenAI model kept for compatibility
USE_GPT5_MODELS = False                                 # Toggle for GPT-5 models (default: GPT-4.1)
GPT5_USE_HIGH_REASONING_ON_RETRY = True                # Use high reasoning effort after first failure (instead of model switch)

# --- Combat System Settings ---
USE_COMPRESSED_COMBAT = True                            # Toggle for compressed combat AND validation prompts (False = original prompts)
COMBAT_API_TIMEOUT_SECONDS = 120                        # Per-call timeout for combat LLM calls (prevents indefinite hangs)
COMBAT_CONNECT_TIMEOUT_SECONDS = 10                     # TCP connection timeout for combat LLM calls
COMBAT_FAST_DETERMINISTIC_NARRATION = True             # Fast-path local narration for deterministic PC_PHASE commands
COMBAT_PC_PHASE_NL_FAST_PATH = True                    # Canary enabled; rollback by setting False
DETERMINISTIC_ENEMY_RESOLUTION_ENABLED = False          # Keep enemy resolver off until reviewed G5R PASS and separate rollout approval
COMBAT_ALLY_CONTROLLER_ENABLED = False                  # Ally controller requires the deterministic enemy resolver gate
COMBAT_ALLY_PREFETCH_ENABLED = False                    # Ally prefetch requires both ally-controller gates
COMBAT_TACTICAL_BRAIN_ENABLED = False                   # Commander plans require the deterministic enemy resolver gate
COMBAT_TACTICAL_PREFETCH_ENABLED = False                # PC-phase commander-plan prefetch requires both tactical gates
COMBAT_TACTICAL_PREFETCH_DEADLINE_SECONDS = 120          # Maximum age for a prefetched plan at enemy-batch consume
ENABLE_COMBAT_TURN_TRACE = False                       # Opt-in combat latency trace writer (default OFF)
# TABLETOP MODE: Fault injection is opt-in and runtime-authorized to Capture_Arena copies only.
COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED = False
# TABLETOP MODE: G9 transport-failure injection is opt-in and sandbox-authorized only.
OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED = False

# --- Narrator System Settings ---
NARRATOR_API_TIMEOUT_SECONDS = 120                      # Per-call timeout for narrator LLM calls (prevents indefinite hangs)
NARRATOR_CONNECT_TIMEOUT_SECONDS = 10                   # TCP connection timeout for narrator LLM calls
MODULE_GENERATION_API_TIMEOUT_SECONDS = 120              # Bounds each in-process ModuleBuilder generation call

# --- Streaming UX Settings ---
# TABLETOP MODE: Reversion defaults - keep stable block narration UX.
ENABLE_CHAT_STREAMING = False                          # Reversion default: keep canonical block narration path
ENABLE_BROWSER_TTS_STREAM_SYNC = False                 # Reversion default: disable sentence-level stream TTS
STREAM_SUPERSEDED_VISIBLE = False                      # Hide superseded draft attempts by default for cleaner UX

# --- TTS Text Sync Settings ---
# TABLETOP MODE: Browser word-boundary sync for progressive text reveal (OFF by default).
# When enabled, narration text reveals word-by-word synchronized with Browser TTS speech.
ENABLE_BROWSER_WORD_SYNC = False                       # Browser TTS word-boundary synchronized text reveal
# Future: Non-browser TTS timing estimation (Phase 2 - scaffold only, not active)
ENABLE_TTS_ESTIMATED_TIMING = False                    # Estimated timing sync for OpenAI TTS (future Phase 2)

# --- Session Diary Generation ---
ENABLE_SESSION_DIARY_LLM = True                       # Use LLM prompt path for diary checkpoints; fallback remains deterministic
ENABLE_PLAYERS_DIARY_APPEND_LLM = True                # Use LLM append/rebuild path for players diary markdown artifact

# --- Accurate Ingest Settings ---
# TABLETOP MODE: Enable multipass section extraction, identity adjudication,
# plot topology synthesis, and source-graph packet synthesis before the legacy
# one-shot normalizer. Set to False to use only legacy one-shot normalization.
ENABLE_ACCURATE_INGEST_MULTI_PASS = True              # Multi-pass source-faithful normalization for readable Homebrew uploads
ENABLE_NORMALIZATION_FIDELITY_AUDIT = True            # Compare normalized packet against source artifacts
ENABLE_NORMALIZATION_FIDELITY_REPAIR = True           # Run bounded repair loop for repairable fidelity gaps
NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS = 3        # Max repair attempts before giving up
ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF = True       # Generate source-locked builder blueprint and narrative (Phase 4)
ENABLE_ACCURATE_INGEST_FIDELITY_REVIEW_PANEL = False   # Pause accurate-ingest uploads for source-fidelity review before build (default: OFF)
ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES = True    # Compare generated module against source/blueprint artifacts (Phase 6)
# Accurate-ingest GUI default authoring path: existing ModuleBuilder orchestration with
# source-enhanced input. Seed writer remains available as support/fallback/preview tooling
# behind ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK.
ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False   # Blueprint-native deterministic seed + bounded enrichment for accurate-ingest GUI builds (Phase 12; default OFF)
ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK = False  # Explicit seed-writer fallback/preview mode (support tooling, not default author)
ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT = False  # Bounded LLM enrichment pass over seeded module fields (Phase 12; requires GUI_BLUEPRINT_BUILD)

# --- LLM Adaptation Lane (rollout gated) ---
# LLM-led adaptation of readable Homebrew sources into NEQ-TTRPG modules.
# Disabled by default: the legacy accurate-ingest path remains the default
# route until the adaptation lane is fully validated and rollout explicitly
# enables this flag. Invalid or missing values resolve safely to False
# (legacy behavior). Rollback: set to False, no code removal needed.
ENABLE_LLM_ADAPTATION = True
# Separate opt-in for canonical monster stat generation; keep disabled until
# approved-identity, schema, and staging-only rollout checks are complete.
ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = True
# Maximum semantic adaptation revisions after the initial build. Values above
# the hard limit of two are clamped by the provider-free revision orchestrator.
LLM_ADAPTATION_MAX_REVISIONS = 1

# --- Conversation Compression Settings ---
# Enable/disable compression types before API calls
COMPRESSION_ENABLED = True                              # Master switch for all compression
COMPRESS_LOCATION_ENCOUNTERS = True                     # Compress location encounter data using dynamic compressor
COMPRESS_LOCATION_SUMMARIES = True                      # Compress location summaries (now implemented)
VALIDATION_COMPRESSION_MIN_CHARS = 12000                # Compress validation context only when payload size crosses threshold

# --- Compression Model Configuration ---
# Models used for compressing conversation history and location data
NARRATIVE_COMPRESSION_MODEL = OPENAI_FALLBACK_MODEL  # For general narrative compression
LOCATION_COMPRESSION_MODEL = OPENAI_FALLBACK_MODEL        # For location encounter compression
COMPRESSION_MAX_WORKERS = 4                              # Number of parallel workers for compression

# --- Text-to-Speech Configuration ---
TTS_MODEL = "tts-1"                                       # OpenAI TTS model (tts-1 or tts-1-hd for higher quality)
TTS_VOICE = "fable"                                       # Voice: alloy, echo, fable, onyx, nova, shimmer (fable is good for narration)
TTS_SPEED = 1.0                                           # Speed: 0.25 to 4.0 (1.0 is normal)

# ============================================================================
# OPENROUTER CONFIGURATION - Multi-Provider AI Support
# ============================================================================

# --- Provider Selection ---
# Set to "openrouter" to use OpenRouter, "openai" for direct OpenAI API
LLM_PROVIDER = "openrouter"  # Options: "openai", "openrouter"

# --- Chat Model Profiles ---
# Auto is a virtual OpenRouter model; the downstream model is selected by the
# provider. Keep the default tiers model-agnostic and unpriced until a provider
# response supplies the actual model and cost.
MODEL_PROFILES = {
    "production-auto": {
        "complex": {
            "model": "openrouter/auto",
            "params": {},
            "provider": {},
            "price_per_1k": {},
        },
        "simple": {
            "model": "openrouter/auto",
            "params": {},
            "provider": {},
            "price_per_1k": {},
        },
    },
    "titan-auto": {
        "complex": {
            "model": "openrouter/auto",
            "params": {},
            "provider": {},
            "price_per_1k": {},
        },
        "simple": {
            "model": "openrouter/auto",
            "params": {},
            "provider": {},
            "price_per_1k": {},
        },
    },
    "openai/fallback": {
        "complex": {
            "model": OPENAI_FALLBACK_MODEL,
            "params": {},
            "provider": {},
            "price_per_1k": {},
        },
        "simple": {
            "model": OPENAI_FALLBACK_MODEL,
            "params": {},
            "provider": {},
            "price_per_1k": {},
        },
    },
}

# Concrete profile data used for safe unknown/missing-profile degradation.
DEFAULT_PROFILE = MODEL_PROFILES["production-auto"]
ACTIVE_PROFILE = "production-auto"

# narrator and response-validation tasks use a broader Auto Router band;
# every other task keeps OpenRouter Auto's implicit low-band default.
AUTO_ROUTER_TASK_COST_TIERS = {
    "dm_main": "medium",
    "dm_validation": "medium",
    "combat_validation": "medium",
    "validation": "medium",
    "character_validator": "medium",
    "safety_review": "medium",
    "toolkit_adaptation_semantic_auditor": "medium",
}

# --- OpenRouter Settings ---
# Get your API key at: https://openrouter.ai/keys
OPENROUTER_API_KEY = ""  # Set in config.py (not model_config.py)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_HTTP_REFERER = "https://github.com/zeug/NeverEndingQuest"  # For OpenRouter rankings
OPENROUTER_APP_TITLE = "NeverEndingQuest AI DM"

# --- Pre-configured Models ---
# Recommended: Kimi K2.5 for DM (excellent reasoning, 1M context)
# Deprecated: use ACTIVE_PROFILE and MODEL_PROFILES instead.
OPENROUTER_CHAT_MODEL = "moonshotai/kimi-k2.5"

# Alternative models (uncomment to use):
# OPENROUTER_CHAT_MODEL = "anthropic/claude-3.5-sonnet"  # If you prefer Claude
# OPENROUTER_CHAT_MODEL = "google/gemini-2.0-flash-exp"  # Fastest option
# OPENROUTER_CHAT_MODEL = "openai/gpt-5.4-mini-2026-03-17"    # Use OpenAI via OpenRouter

# --- Future Provider Slots (Phase 2+ Prep) ---
IMAGE_PROVIDER = "openai"  # Options: "openai", "openrouter", "stability"
TTS_PROVIDER = "openai"    # Options: "openai", "openrouter", "elevenlabs"
VIDEO_PROVIDER = "none"    # Options: "none", "openrouter" (Phase 3)

# --- Fallback Configuration ---
ENABLE_PROVIDER_FALLBACK = True  # Auto-fallback to OpenAI if OpenRouter fails
FALLBACK_NOTIFICATION = True     # Show system message in GUI when fallback occurs
MAX_FALLBACK_ATTEMPTS = 3        # Retry OpenRouter before falling back

# ============================================================================
# PHASE 1B: FULL OPENROUTER ENABLEMENT - 3-TIER MODEL SYSTEM
# ============================================================================
#
# TIER 1: Kimi K2.5 with Thinking Toggle (PRIMARY - Recommended)
#   - Uses one model with adjustable reasoning depth
#   - thinking: enabled = Complex tasks (matches upstream gpt-4.1-full)
#   - thinking: disabled = Simple tasks (matches upstream gpt-4.1-mini)
#   - Best balance of cost, quality, and simplicity
#
# TIER 2: Dual Model Strategy (SECONDARY - Fallback)
#   - Uses separate models for complex vs simple tasks
#   - Kimi K2.5 for full tasks, Gemini Flash for mini tasks
#   - Use if Kimi thinking toggle has issues
#
# TIER 3: OpenAI Upstream (TERTIARY - Compatibility)
#   - Uses original OpenAI model constants
#   - Automatic fallback when OpenRouter fails
#   - 100% upstream compatibility maintained
#
# To switch strategies, just change OPENROUTER_STRATEGY below
# ============================================================================

# --- Strategy Selection ---
# "kimi_thinking" = One model with thinking toggle (recommended, default)
# "dual_model" = Separate models for full/mini tasks (fallback option)
# "single_model" = One model for everything (not recommended)
# Deprecated: use ACTIVE_PROFILE and MODEL_PROFILES for profile selection.
OPENROUTER_STRATEGY = "kimi_thinking"

# --- Base Models ---
# Deprecated: use MODEL_PROFILES[...]["complex"]["model"] instead.
OPENROUTER_FULL_MODEL = "moonshotai/kimi-k2.5"  # For complex reasoning tasks
# Deprecated: use MODEL_PROFILES[...]["simple"]["model"] instead.
OPENROUTER_MINI_MODEL = "google/gemini-2.0-flash-exp"  # For simple tasks (dual_model only)

# Alternative mini models (uncomment to use):
# OPENROUTER_MINI_MODEL = "qwen/qwen-2.5-7b-instruct"  # Cheapest option
# OPENROUTER_MINI_MODEL = "meta-llama/llama-3.3-70b-instruct"  # Balanced quality/cost

# --- Task Mapping (Based on Upstream Model Assignments) ---
# Tasks using GPT-4.1-full upstream -> thinking: enabled
# Tasks using GPT-4.1-mini upstream -> thinking: disabled
# 
# This mapping preserves upstream's tested model assignments

# TABLETOP MODE: Canonical task-tier data for retained legacy profile selection.
COMPLEX_TASKS = [
    # Complex reasoning tasks (upstream used gpt-4.1-full)
    "dm_main",              # Main DM responses
    "dm_validation",        # Response validation
    "combat_main",          # Combat simulation
    "action_prediction",    # Action prediction
    "character_validator",  # Character validation
    "npc_builder",          # NPC generation
    "monster_builder",      # Monster generation
    "level_up",             # Level up processing
    "dm_full",              # Complex actions with JSON
    "location_compression", # Location data compression
]

# All other tasks default to thinking: disabled (upstream used gpt-4.1-mini)
# Including: summaries, updates, compression, transitions, builders (mini tasks)

# --- Task-Specific Overrides (Optional) ---
# Force specific configuration for individual tasks
# Format: "task_id": {"thinking": "enabled|disabled", "model": "model_id"}
# Uncomment lines below to override defaults:
TASK_OVERRIDES = {
    # Titan has its own profile seam; narrator and combat remain independently
    # overrideable by adding dm_main or combat_main entries here.
    "titan_cycle": {"profile": "titan-auto"},
    # Example overrides:
    # "combat_main": {"thinking": "disabled"},  # Try faster combat
    # "summaries": {"thinking": "enabled"},     # Try better summaries
    # "validation": {"model": "anthropic/claude-3.5-sonnet"},  # Use Claude for validation
}

# --- Temperature Settings by Task Type ---
# These match upstream temperature preferences
TASK_TEMPERATURES = {
    "dm_main": 0.7,
    "dm_validation": 0.1,  # Low temp for validation
    "combat_main": 0.7,
    "action_prediction": 0.7,
    "validation": 0.3,     # Low temp for analytical tasks
    "summaries": 0.8,
    "updates": 0.7,
    "compression": 0.3,
    "builders": 0.7,
    "default": 0.7,
}

# Task-family policy for the production LLM facade. Reasoning entries omit
# temperature/top_p so direct reasoning-model request shape stays unchanged.
# Non-reasoning temperatures use TASK_TEMPERATURES where present; otherwise
# they use the pre-G6 caller consensus documented in the activation design.
# top_p remains omitted except for compression, whose existing task callers
# defined the neutral value explicitly.
TASK_POLICY_SAMPLING = {
    "action_prediction": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "adventure_summary": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "builders": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "character_validator": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.1},
    },
    "combat_main": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "combat_summary": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "combat_validation": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.3},
    },
    "compression": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {
            "family": "non_reasoning",
            "temperature": 0.3,
            "top_p": 1.0,
        },
    },
    "dm_main": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "dm_mini": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.4},
    },
    "dm_validation": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.1},
    },
    "encounter_update": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "generate_area_description": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "generate_area_name": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "generate_thematic_names": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "level_up": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "location_compression": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.1},
    },
    "location_generator": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "location_generator_batch": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "location_summarizer": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "module_generator": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "monster_builder": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "npc_builder": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.1},
    },
    "npc_name_canonicalizer": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.0},
    },
    "parse_module_params": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.3},
    },
    "plot_generator": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "plot_update": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "prompt_sanitizer": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.3},
    },
    "safety_review": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "storage_processor": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.1},
    },
    "summaries": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.8},
    },
    "travel_narration": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "unify_plots": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "update_plot_hooks": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.6},
    },
    "updates": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "validation": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.3},
    },
    "toolkit_adaptation_author": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "toolkit_adaptation_convergence": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "toolkit_adaptation_semantic_auditor": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
    "toolkit_final_reconciliation": {
        "reasoning": {"family": "reasoning"},
        "non_reasoning": {"family": "non_reasoning", "temperature": 0.7},
    },
}

# --- Migration Path Notes ---
# Current: Kimi K2.5 with thinking toggle (smart cost/quality balance)
# Future Phase 2: When cheap models mature, move tasks to dual_model
# Future Phase 3: When one model is "good enough", use single_model
# 
# To migrate: Just change OPENROUTER_STRATEGY and restart server
# No code changes needed - all routing happens in ai_client_factory.py

# ============================================================================
# TABLETOP MODE: Missing Media Warning Throttle Settings
# ============================================================================
# Per-key throttle to prevent warning log spam for repeated media misses.
# 
# Rationale:
# - Preserves first-miss diagnostics while reducing noise for repeated requests
# - Thread-safe for multi-threaded Flask web server
# - Zero impact on media serving behavior (still returns 404 on miss)
#
MISSING_MEDIA_WARNING_THROTTLE_ENABLED = True  # Master switch for throttle
MISSING_MEDIA_WARNING_THROTTLE_SECONDS = 300   # Window in seconds (5 minutes)
# ============================================================================

# ============================================================================
# TABLETOP MODE: Module Ingest Watch Folder Settings
# ============================================================================
# Watches modules/ingest for new source files and auto-ingests them into modules.
# Processed files are archived to modules/ingest/archive with a result sidecar.
ENABLE_MODULE_INGEST_WATCH = True
MODULE_INGEST_WATCH_DIR = "modules/ingest"
MODULE_INGEST_ARCHIVE_DIR = "modules/ingest/archive"
MODULE_INGEST_POLL_INTERVAL_SECONDS = 5.0
MODULE_INGEST_ALLOWED_EXTENSIONS = [".md", ".markdown", ".txt"]
MODULE_INGEST_STRICT_VALIDATION = True
# ============================================================================

# ============================================================================
# TABLETOP MODE: LLM Usage Tracking and Cost Estimation
# ============================================================================
# Provider-agnostic usage tracking with session/week rollups and cost estimation.
# Works with OpenAI, OpenRouter, and any OpenAI-compatible API.

# USD to NZD conversion rate for cost display
USD_TO_NZD_RATE = 1.65  # Default rate; update as needed

# Rolling week window size in days
USAGE_WEEK_WINDOW_DAYS = 7

# Blended fallback USD cost per 1M tokens (prompt + completion combined)
# Used only when provider does not return per-call cost in usage metadata
# Set to 0.0 to disable fallback estimation (cost will show as unavailable)
USD_PER_1M_TOKENS_BLEND = 1.50  # Conservative blended estimate

# DALL-E 3 per-image pricing (USD) - used when provider cost metadata is unavailable
# Configured per size and quality to match OpenAI's published pricing
DALLE3_PRICING_USD = {
    "1024x1024": {
        "standard": 0.040,
        "hd": 0.080
    },
    "1024x1792": {
        "standard": 0.080,
        "hd": 0.120
    },
    "1792x1024": {
        "standard": 0.080,
        "hd": 0.120
    }
}

# GPT-Image-1 per-image pricing (USD) - used when provider cost metadata is unavailable
# gpt-image-1 uses token-based pricing; these are approximate USD estimates per image
GPT_IMAGE_1_PRICING_USD = {
    "1024x1024": {
        "low": 0.011,
        "medium": 0.042,
        "high": 0.167
    },
    "1024x1792": {
        "low": 0.022,
        "medium": 0.083,
        "high": 0.333
    },
    "1792x1024": {
        "low": 0.022,
        "medium": 0.083,
        "high": 0.333
    }
}

# Feature Flags -- Toolkit LLM Classification
# When True, the module toolkit build path invokes LLM-assisted narrative classification
# for ambiguous entities, destination phrases, and NPC visibility after deterministic
# enrichment but before publishability audit. When False, the build path is purely
# deterministic (backward compatible with pre-Phase-2 behavior). Default: True.
# Rollback: set to False, no code removal needed. All LLM calls are advisory and
# fail-open; Python validates all labels against strict enum contracts.
ENABLE_LLM_CLASSIFICATION = True

# Feature Flag -- Accurate-Ingest Final Benchmark and Publication Gate
# When True, the publishability audit integrates source-fidelity benchmark
# results (from accurate_ingest_benchmark_report.json) into the final
# publishable determination. When False, source-fidelity checks are
# treated as unknown (non-blocking). Default: True.
# Rollback: set to False, no code removal needed.
ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK = True
# ============================================================================
