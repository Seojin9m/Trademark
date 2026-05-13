"""Risk profile: maps aggressiveness level (1-5) to trading parameters."""


RISK_PROFILES = {
    1: {
        "label": "Conservative",
        "buy_min_decile": 9,
        "min_decile_change": 3,
        "position_size_scalar": 0.7,
        "chase_threshold": 0.03,
        "chase_mode": "strict",
        "drawdown_alert": -0.10,
        "drawdown_halt": -0.15,
        "max_single_position": 0.07,
        "allowed_risk_tiers": ["standard"],
    },
    2: {
        "label": "Cautious",
        "buy_min_decile": 9,
        "min_decile_change": 3,
        "position_size_scalar": 0.85,
        "chase_threshold": 0.04,
        "chase_mode": "strict",
        "drawdown_alert": -0.12,
        "drawdown_halt": -0.18,
        "max_single_position": 0.08,
        "allowed_risk_tiers": ["standard"],
    },
    3: {
        "label": "Balanced",
        "buy_min_decile": 8,
        "min_decile_change": 2,
        "position_size_scalar": 1.0,
        "chase_threshold": 0.05,
        "chase_mode": "gradient",
        "drawdown_alert": -0.15,
        "drawdown_halt": -0.20,
        "max_single_position": 0.10,
        "allowed_risk_tiers": ["standard", "moderate_risk"],
    },
    4: {
        "label": "Growth",
        "buy_min_decile": 8,
        "min_decile_change": 2,
        "position_size_scalar": 1.2,
        "chase_threshold": 0.07,
        "chase_mode": "allow",
        "drawdown_alert": -0.20,
        "drawdown_halt": -0.25,
        "max_single_position": 0.12,
        "allowed_risk_tiers": ["standard", "moderate_risk", "high_risk"],
    },
    5: {
        "label": "Aggressive",
        "buy_min_decile": 7,
        "min_decile_change": 1,
        "position_size_scalar": 1.4,
        "chase_threshold": 0.10,
        "chase_mode": "allow",
        "drawdown_alert": -0.25,
        "drawdown_halt": -0.30,
        "max_single_position": 0.15,
        "allowed_risk_tiers": ["standard", "moderate_risk", "high_risk"],
    },
}


def get_risk_adjustments(risk_level: int = 3) -> dict:
    """Return the parameter overrides for a given risk level (1-5)."""
    level = max(1, min(5, risk_level))
    return RISK_PROFILES[level].copy()
