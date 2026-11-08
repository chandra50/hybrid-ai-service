"""Static reference data for the simulated fleet.

All manufacturers, model names and part numbers are fictional.
Depot coordinates are real California cities so distances/drive times are
plausible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Signal:
    name: str
    unit: str
    baseline: float
    noise: float
    warn: float | None = None  # alarm thresholds (upper unless low_is_bad)
    trip: float | None = None
    low_is_bad: bool = False


@dataclass(frozen=True)
class FailureMode:
    code: str
    description: str
    severity: str  # low | medium | high | critical
    symptoms: tuple[str, ...]
    effects: dict[str, float]  # signal -> fractional drift at full progression (+0.6 = +60%)
    parts: tuple[tuple[str, int], ...]  # (part_number, qty)
    skills: tuple[str, ...]
    est_hours: float
    needs_workshop: bool = False
    safety_critical: bool = False
    procedure: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetModel:
    model: str
    category: str
    manufacturer: str
    portable: bool
    signals: tuple[Signal, ...]
    failure_modes: tuple[FailureMode, ...]
    parts: dict[str, str] = field(default_factory=dict)  # part_number -> description


DEPOTS = {
    "DEP-SAC": ("Sacramento Valley", "Sacramento", 38.58, -121.49),
    "DEP-FAT": ("Central Valley", "Fresno", 36.74, -119.79),
    "DEP-BFL": ("Kern", "Bakersfield", 35.37, -119.02),
    "DEP-RDD": ("Northern", "Redding", 40.59, -122.39),
    "DEP-BSW": ("Mojave", "Barstow", 34.90, -117.02),
    "DEP-IPL": ("Imperial", "El Centro", 32.79, -115.56),
}
WAREHOUSE = ("WH-STK", "Stockton", 37.96, -121.29)

# Probability a site in this region has good / patchy / no cellular coverage.
COVERAGE_BY_REGION = {
    "Sacramento Valley": (0.75, 0.20, 0.05),
    "Central Valley": (0.55, 0.35, 0.10),
    "Kern": (0.50, 0.35, 0.15),
    "Northern": (0.35, 0.40, 0.25),
    "Mojave": (0.30, 0.40, 0.30),
    "Imperial": (0.45, 0.40, 0.15),
}

SKILLS = (
    "mechanical",
    "electrical",
    "rotating_equipment",
    "hydraulics",
    "diesel",
    "controls",
    "hv_certified",
    "climbing_cert",
    "confined_space",
)

HAZARDS = (
    "high ambient heat (>40C) in summer",
    "wildfire risk area - check red flag warnings",
    "rattlesnakes reported near enclosure",
    "unpaved access road, 4x4 recommended",
    "locked gate - code in site notes",
    "overhead power lines near crane path",
    "confined space entry required for pit",
)

FIRST_NAMES = (
    "Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey", "Riley", "Jamie",
    "Avery", "Quinn", "Rowan", "Devon", "Reese", "Skyler", "Cameron", "Drew",
    "Emerson", "Hayden", "Kendall", "Logan", "Parker", "Sage", "Toni", "Robin",
)
LAST_NAMES = (
    "Alvarez", "Nguyen", "Patel", "Kim", "Okafor", "Silva", "Chen", "Garcia",
    "Hernandez", "Singh", "Martinez", "Lopez", "Ramirez", "Tran", "Cruz", "Flores",
    "Rivera", "Wong", "Morales", "Reyes", "Lee", "Torres", "Diaz", "Castillo",
)

LOTO_STEPS = (
    "Notify site operator and control room before shutdown.",
    "Shut down the equipment using the normal stop sequence.",
    "Isolate all energy sources (electrical, hydraulic, pneumatic, stored mechanical).",
    "Apply personal lock and tag to each isolation point.",
    "Release or block stored energy; verify zero energy state with a test.",
    "Attempt restart to confirm isolation, then return controls to off.",
)

MODELS: tuple[AssetModel, ...] = (
    AssetModel(
        model="PMP-CENT-400",
        category="centrifugal pump",
        manufacturer="Sierra Pumpworks",
        portable=True,
        signals=(
            Signal("vibration_rms", "mm/s", 2.5, 0.25, warn=7.1, trip=11.0),
            Signal("bearing_temp", "degC", 55.0, 1.5, warn=85.0, trip=95.0),
            Signal("discharge_pressure", "bar", 8.0, 0.2, warn=6.0, trip=5.0, low_is_bad=True),
            Signal("motor_current", "A", 42.0, 1.0, warn=52.0, trip=58.0),
        ),
        parts={
            "P-PMP-0101": "Bearing kit, drive end + non-drive end",
            "P-PMP-0102": "Mechanical seal cartridge 60mm",
            "P-PMP-0103": "Impeller 320mm, duplex SS",
            "P-PMP-0104": "Coupling insert set",
            "P-PMP-0105": "Motor thermal overload relay",
        },
        failure_modes=(
            FailureMode(
                "PMP-BRG-WEAR", "Bearing wear / lubrication breakdown", "high",
                ("grinding noise from bearing housing", "rising vibration", "hot bearing housing"),
                {"vibration_rms": 1.8, "bearing_temp": 0.45},
                (("P-PMP-0101", 1), ("P-PMP-0104", 1)),
                ("mechanical", "rotating_equipment"), 5.0,
                procedure=("Check lubrication level and grease condition.",
                           "Measure vibration spectrum at DE/NDE; look for bearing defect frequencies.",
                           "Replace bearing kit; check shaft alignment within 0.05 mm."),
            ),
            FailureMode(
                "PMP-SEAL-LEAK", "Mechanical seal leak", "medium",
                ("visible leak at seal gland", "puddle under pump", "slight pressure drop"),
                {"discharge_pressure": -0.12},
                (("P-PMP-0102", 1),),
                ("mechanical",), 3.0,
                procedure=("Confirm leak source is the seal, not casing gasket.",
                           "Replace seal cartridge; set seal per manual torque table."),
            ),
            FailureMode(
                "PMP-IMP-CAV", "Impeller cavitation damage", "high",
                ("crackling / gravel noise", "low discharge pressure", "fluctuating flow"),
                {"discharge_pressure": -0.3, "vibration_rms": 0.9, "motor_current": -0.08},
                (("P-PMP-0103", 1), ("P-PMP-0102", 1)),
                ("mechanical", "rotating_equipment"), 10.0, needs_workshop=True,
                procedure=("Check suction strainer and NPSH margin.",
                           "Pull rotating assembly; inspect impeller vanes for pitting.",
                           "Replace impeller and seal at workshop; balance rotor."),
            ),
            FailureMode(
                "PMP-MTR-OVL", "Motor overload trips", "medium",
                ("pump trips on overload", "motor hot to touch", "high current"),
                {"motor_current": 0.32},
                (("P-PMP-0105", 1),),
                ("electrical",), 2.5,
                procedure=("Measure phase currents and insulation resistance.",
                           "Verify overload setting vs nameplate FLA; replace relay if faulty."),
            ),
        ),
    ),
    AssetModel(
        model="CMP-SCR-75",
        category="rotary screw air compressor",
        manufacturer="Golden State Air Systems",
        portable=True,
        signals=(
            Signal("discharge_temp", "degC", 82.0, 1.5, warn=105.0, trip=115.0),
            Signal("oil_pressure", "bar", 4.2, 0.1, warn=3.0, trip=2.2, low_is_bad=True),
            Signal("vibration_rms", "mm/s", 3.0, 0.3, warn=7.1, trip=11.0),
            Signal("motor_current", "A", 120.0, 2.5, warn=140.0, trip=152.0),
        ),
        parts={
            "P-CMP-0201": "Oil filter element",
            "P-CMP-0202": "Air-end rebuild kit",
            "P-CMP-0203": "Intake valve assembly",
            "P-CMP-0204": "Synthetic compressor oil, 20 L",
        },
        failure_modes=(
            FailureMode(
                "CMP-OIL-FILT", "Clogged oil filter", "medium",
                ("high discharge temperature", "filter differential alarm"),
                {"discharge_temp": 0.22, "oil_pressure": -0.25},
                (("P-CMP-0201", 1), ("P-CMP-0204", 1)),
                ("mechanical",), 1.5,
                procedure=("Check oil filter differential pressure.",
                           "Replace filter element and top up oil."),
            ),
            FailureMode(
                "CMP-AIR-END", "Worn air-end rotors", "high",
                ("loss of capacity", "metallic knocking", "high vibration"),
                {"vibration_rms": 1.5, "discharge_temp": 0.15, "motor_current": 0.12},
                (("P-CMP-0202", 1), ("P-CMP-0204", 2)),
                ("mechanical", "rotating_equipment"), 16.0, needs_workshop=True,
                procedure=("Confirm with capacity test and vibration spectrum.",
                           "Swap with exchange unit if available; rebuild air-end at workshop."),
            ),
            FailureMode(
                "CMP-VLV-INT", "Intake valve sticking", "low",
                ("compressor does not load", "short cycling"),
                {"motor_current": -0.2},
                (("P-CMP-0203", 1),),
                ("mechanical", "controls"), 2.0,
                procedure=("Check control air signal to intake valve.",
                           "Clean or replace intake valve assembly."),
            ),
        ),
    ),
    AssetModel(
        model="GEN-DSL-500",
        category="diesel standby generator",
        manufacturer="Pacific Powerworks",
        portable=False,
        signals=(
            Signal("coolant_temp", "degC", 85.0, 1.0, warn=98.0, trip=104.0),
            Signal("oil_pressure", "bar", 4.5, 0.1, warn=2.5, trip=1.8, low_is_bad=True),
            Signal("output_voltage", "V", 480.0, 2.0, warn=456.0, trip=440.0, low_is_bad=True),
            Signal("frequency", "Hz", 60.0, 0.05, warn=59.3, trip=58.8, low_is_bad=True),
        ),
        parts={
            "P-GEN-0301": "Fuel injector",
            "P-GEN-0302": "Radiator hose kit",
            "P-GEN-0303": "Automatic voltage regulator (AVR)",
            "P-GEN-0304": "Coolant concentrate, 20 L",
        },
        failure_modes=(
            FailureMode(
                "GEN-INJ-FAULT", "Fuel injector fault", "medium",
                ("black smoke", "rough running", "frequency hunting"),
                {"frequency": -0.012, "coolant_temp": 0.05},
                (("P-GEN-0301", 2),),
                ("diesel", "mechanical"), 4.0,
                procedure=("Run cylinder cut-out test to locate injector.",
                           "Replace injectors; bleed fuel system."),
            ),
            FailureMode(
                "GEN-COOL-LEAK", "Coolant leak / overheating", "high",
                ("coolant puddle", "high temperature alarm", "steam from radiator"),
                {"coolant_temp": 0.2},
                (("P-GEN-0302", 1), ("P-GEN-0304", 1)),
                ("diesel", "mechanical"), 3.0, safety_critical=True,
                procedure=("Do not open radiator cap while hot.",
                           "Pressure-test cooling system; replace failed hoses; refill and bleed."),
            ),
            FailureMode(
                "GEN-AVR-FAIL", "Voltage regulator failure", "high",
                ("unstable output voltage", "load transfer failures"),
                {"output_voltage": -0.07},
                (("P-GEN-0303", 1),),
                ("electrical", "controls"), 3.0,
                procedure=("Check excitation voltage and sensing leads.",
                           "Replace AVR; set voltage and stability per manual."),
            ),
        ),
    ),
    AssetModel(
        model="XFM-PAD-2500",
        category="pad-mounted transformer",
        manufacturer="Coastal Electric Apparatus",
        portable=False,
        signals=(
            Signal("oil_temp", "degC", 60.0, 1.0, warn=90.0, trip=105.0),
            Signal("load_pct", "%", 65.0, 3.0, warn=100.0, trip=120.0),
            Signal("dissolved_gas_ppm", "ppm", 120.0, 5.0, warn=400.0, trip=700.0),
        ),
        parts={
            "P-XFM-0401": "Transformer oil, 200 L drum",
            "P-XFM-0402": "HV bushing 15kV",
            "P-XFM-0403": "Tap changer contact kit",
        },
        failure_modes=(
            FailureMode(
                "XFM-OIL-DEGR", "Insulating oil degradation", "medium",
                ("rising dissolved gas", "dark oil in sight glass"),
                {"dissolved_gas_ppm": 2.5, "oil_temp": 0.15},
                (("P-XFM-0401", 1),),
                ("electrical", "hv_certified"), 6.0,
                procedure=("Take oil sample for DGA lab analysis.",
                           "Filter or replace oil per DGA result."),
            ),
            FailureMode(
                "XFM-BUSH-CRACK", "Cracked HV bushing", "critical",
                ("visible crack on bushing", "partial discharge noise", "arc marks"),
                {"dissolved_gas_ppm": 4.5, "oil_temp": 0.3},
                (("P-XFM-0402", 1), ("P-XFM-0401", 1)),
                ("electrical", "hv_certified"), 8.0, safety_critical=True,
                procedure=("De-energize and ground per utility switching order.",
                           "Replace bushing; HV test before re-energizing."),
            ),
            FailureMode(
                "XFM-TAP-CHG", "Tap changer contact wear", "medium",
                ("voltage out of band", "tap changer noise"),
                {"oil_temp": 0.1, "dissolved_gas_ppm": 1.0},
                (("P-XFM-0403", 1),),
                ("electrical", "hv_certified"), 5.0,
                procedure=("Check tap position indicator and contact resistance.",
                           "Replace contact kit."),
            ),
        ),
    ),
    AssetModel(
        model="WTG-GBX-2M",
        category="wind turbine (2 MW) drivetrain",
        manufacturer="Tehachapi Wind Systems",
        portable=False,
        signals=(
            Signal("gearbox_oil_temp", "degC", 58.0, 1.5, warn=75.0, trip=85.0),
            Signal("vibration_rms", "mm/s", 1.8, 0.2, warn=4.5, trip=7.1),
            Signal("rotor_rpm", "rpm", 14.0, 0.4),
            Signal("power_kw", "kW", 1400.0, 80.0),
        ),
        parts={
            "P-WTG-0501": "Gearbox intermediate-shaft bearing",
            "P-WTG-0502": "Pitch actuator",
            "P-WTG-0503": "Yaw drive motor",
            "P-WTG-0504": "Gearbox oil, 200 L",
        },
        failure_modes=(
            FailureMode(
                "WTG-GBX-BRG", "Gearbox bearing damage", "high",
                ("rising gearbox temperature", "high vibration", "metal particles in oil"),
                {"gearbox_oil_temp": 0.3, "vibration_rms": 2.0},
                (("P-WTG-0501", 1), ("P-WTG-0504", 1)),
                ("mechanical", "rotating_equipment", "climbing_cert"), 24.0,
                procedure=("Inspect oil debris sensor and take oil sample.",
                           "Borescope inspection through inspection port.",
                           "Up-tower bearing replacement (crane may be required)."),
            ),
            FailureMode(
                "WTG-PITCH-ACT", "Pitch actuator fault", "medium",
                ("pitch asymmetry alarm", "reduced power output"),
                {"power_kw": -0.3},
                (("P-WTG-0502", 1),),
                ("hydraulics", "controls", "climbing_cert"), 6.0,
                procedure=("Check pitch system hydraulic pressure and accumulator.",
                           "Replace actuator; recalibrate blade angle."),
            ),
            FailureMode(
                "WTG-YAW-MTR", "Yaw motor failure", "low",
                ("nacelle not tracking wind", "yaw error alarm"),
                {"power_kw": -0.15},
                (("P-WTG-0503", 1),),
                ("electrical", "climbing_cert"), 5.0,
                procedure=("Check yaw motor brake and contactor.",
                           "Replace yaw motor."),
            ),
        ),
    ),
)

MODELS_BY_NAME = {m.model: m for m in MODELS}


def failure_mode(code: str) -> tuple[AssetModel, FailureMode]:
    for m in MODELS:
        for fm in m.failure_modes:
            if fm.code == code:
                return m, fm
    raise KeyError(code)


def all_parts() -> dict[str, str]:
    out: dict[str, str] = {}
    for m in MODELS:
        out.update(m.parts)
    return out

# Unit prices (USD) for approval rules. Fictional.
PART_PRICES = {
    "P-PMP-0101": 420, "P-PMP-0102": 780, "P-PMP-0103": 2350, "P-PMP-0104": 95, "P-PMP-0105": 260,
    "P-CMP-0201": 85, "P-CMP-0202": 6400, "P-CMP-0203": 690, "P-CMP-0204": 310,
    "P-GEN-0301": 540, "P-GEN-0302": 160, "P-GEN-0303": 1150, "P-GEN-0304": 120,
    "P-XFM-0401": 1300, "P-XFM-0402": 2900, "P-XFM-0403": 1750,
    "P-WTG-0501": 5200, "P-WTG-0502": 3800, "P-WTG-0503": 2100, "P-WTG-0504": 1450,
}
