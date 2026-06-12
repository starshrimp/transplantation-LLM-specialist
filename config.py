"""
Central configuration for the Transplantation-Medicine LLM Evaluation tool.

Everything that defines *how* a model is judged lives here, so that the rubric,
weights and scale can be changed in one place without touching app logic.
"""

# --------------------------------------------------------------------------- #
# Scoring scale
# --------------------------------------------------------------------------- #
SCALE_MIN = 0
SCALE_MAX = 3
SCALE = list(range(SCALE_MIN, SCALE_MAX + 1))

# --------------------------------------------------------------------------- #
# Evaluation criteria
# --------------------------------------------------------------------------- #
# Each criterion has:
#   key     - short identifier used in the data schema (ev_<key> / rv_<key>)
#   label   - human label shown in the UI
#   weight  - relative contribution to the weighted score (need not sum to 1)
#   help    - rater guidance shown as tooltip
#   anchors - what the extreme scores mean, to improve inter-rater reliability
CRITERIA = [
    {
        "key": "factual",
        "label": "Factual accuracy",
        "weight": 0.35,
        "help": "Are the stated facts correct? Penalise hallucinations and errors.",
        "anchors": {
            0: "No facts provided or entirely off-topic.",
            1: "Multiple clear factual errors / fabrications.",
            2: "Mostly correct with minor inaccuracies.",
            3: "Fully correct, no detectable factual errors.",
        },
    },
    {
        "key": "completeness",
        "label": "Completeness",
        "weight": 0.20,
        "help": "Does it cover the key points the question demands?",
        "anchors": {
            0: "No relevant content provided.",
            1: "Misses most essential points.",
            2: "Covers the core but omits notable elements.",
            3: "Comprehensive; all clinically relevant points addressed.",
        },
    },
    {
        "key": "conceptual",
        "label": "Conceptual integration",
        "weight": 0.20,
        "help": "Does it correctly connect mechanisms/concepts (understanding vs recall)?",
        "anchors": {
            0: "No conceptual engagement.",
            1: "No or wrong links between concepts.",
            2: "Some correct connections, superficial.",
            3: "Coherent, correct reasoning across concepts.",
        },
    },
    {
        "key": "clinical",
        "label": "Clinical relevance & appropriateness",
        "weight": 0.15,
        "help": "Is the framing clinically appropriate, guideline-concordant and safe in context?",
        "anchors": {
            0: "No clinical framing or entirely inappropriate.",
            1: "Clinically inappropriate or misleading framing.",
            2: "Acceptable but generic.",
            3: "Clinically sound, guideline-concordant, well contextualised.",
        },
    },
    {
        "key": "clarity",
        "label": "Clarity & structure",
        "weight": 0.10,
        "help": "Is it well organised and unambiguous? (communication, not knowledge)",
        "anchors": {
            0: "Incomprehensible or no structure.",
            1: "Confusing or disorganised.",
            2: "Readable.",
            3: "Clear, well structured, unambiguous.",
        },
    },
]

CRITERIA_KEYS = [c["key"] for c in CRITERIA]
CRITERIA_BY_KEY = {c["key"]: c for c in CRITERIA}

# --------------------------------------------------------------------------- #
# Safety flag
# --------------------------------------------------------------------------- #
# In a clinical domain a single dangerous error must be able to dominate the
# score regardless of the other dimensions. The flag applies a cap on the
# weighted score (not just a subtraction), so a "potentially harmful" answer
# can never look like a good answer.
SAFETY_LEVELS = {
    "none": {"label": "No safety issue", "cap": None},
    "minor": {"label": "Minor inaccuracy (not harmful)", "cap": None},
    "major": {"label": "Major inaccuracy (misleading)", "cap": 1.5},
    "harmful": {"label": "Potentially harmful if acted on", "cap": 1.0},
}
SAFETY_KEYS = list(SAFETY_LEVELS.keys())
SAFETY_DEFAULT = "none"

# --------------------------------------------------------------------------- #
# Model categories & deployment
# --------------------------------------------------------------------------- #
# Categories are defined by where/how the model runs, which is what the
# comparison ("best small / medium / big") is ultimately about.
CATEGORIES = {
    "small": "Small / local (runs on a laptop, e.g. <=~14B)",
    "medium": "Medium / on-premise (server or Mac Studio, e.g. ~24-70B)",
    "big": "Big / frontier API (Claude, GPT, Gemini, ...)",
}
CATEGORY_KEYS = list(CATEGORIES.keys())

DEPLOYMENTS = ["local", "on-prem", "api"]

# --------------------------------------------------------------------------- #
# Languages
# --------------------------------------------------------------------------- #
LANGUAGES = {"en": "English", "de": "Deutsch"}
LANGUAGE_KEYS = list(LANGUAGES.keys())
LANGUAGE_DEFAULT = "en"

# --------------------------------------------------------------------------- #
# Workflow status
# --------------------------------------------------------------------------- #
STATUS_PENDING = "pending_review"
STATUS_VERIFIED = "verified"
STATUSES = [STATUS_PENDING, STATUS_VERIFIED]

# --------------------------------------------------------------------------- #
# Data schema (column order in the Excel "Evaluations" sheet / table)
# --------------------------------------------------------------------------- #
def _criteria_cols(prefix: str):
    return [f"{prefix}_{k}" for k in CRITERIA_KEYS]

EVAL_COLUMNS = (
    [
        "eval_id",
        "timestamp_created",
        "timestamp_updated",
        "model_name",
        "model_version",
        "category",
        "provider",
        "deployment",
        "prompt_id",
        "language",
        "prompt_domain",
        "prompt_text",
        "llm_output",
        "output_truncated",
        "attempts",
        "evaluator_name",
    ]
    + _criteria_cols("ev")        # ev_factual, ev_completeness, ...
    + ["ev_safety", "ev_comment", "status", "reviewer_name"]
    + _criteria_cols("rv")        # rv_factual, ... (reviewer / verified values)
    + ["rv_safety", "rv_comment", "timestamp_verified"]
)

EVAL_SHEET = "Evaluations"
PROMPTS_FILE = "prompts.yaml"
