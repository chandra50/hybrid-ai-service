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
        model="CMP-SCR-75",
        category="rotary screw air compressor (75 kW)",
        manufacturer="Golden State Air Systems",
        portable=True,
        signals=(
            Signal("discharge_temp", "degC", 82.0, 1.5, warn=105.0, trip=115.0),
            Signal("oil_pressure", "bar", 4.2, 0.1, warn=3.0, trip=2.2, low_is_bad=True),
            Signal("separator_dp", "bar", 0.35, 0.02, warn=0.7, trip=1.0),
            Signal("vibration_rms", "mm/s", 3.0, 0.3, warn=7.1, trip=11.0),
            Signal("motor_current", "A", 120.0, 2.5, warn=140.0, trip=152.0),
        ),
        parts={
            "P-SCR-0201": "Oil filter element",
            "P-SCR-0202": "Air-end rebuild kit",
            "P-SCR-0203": "Intake valve assembly",
            "P-SCR-0204": "Synthetic compressor oil, 20 L",
            "P-SCR-0205": "Air/oil separator element",
        },
        failure_modes=(
            FailureMode(
                "SCR-OIL-FILT", "Clogged oil filter", "medium",
                ("high discharge temperature", "low oil pressure", "filter differential alarm"),
                {"discharge_temp": 0.32, "oil_pressure": -0.3},
                (("P-SCR-0201", 1), ("P-SCR-0204", 1)),
                ("mechanical",), 1.5,
                procedure=("Check oil filter differential pressure and oil level.",
                           "Replace the oil filter element; pre-fill with fresh oil.",
                           "Top up compressor oil to the sight-glass mark."),
            ),
            FailureMode(
                "SCR-SEP-CLOG", "Clogged air/oil separator", "medium",
                ("oil carryover into air lines", "high separator differential", "higher power draw"),
                {"separator_dp": 1.2, "motor_current": 0.1},
                (("P-SCR-0205", 1),),
                ("mechanical",), 2.0,
                procedure=("Confirm separator differential above 0.7 bar at full load.",
                           "Depressurize the sump; replace the separator element and gasket.",
                           "Check the scavenge line orifice is clear."),
            ),
            FailureMode(
                "SCR-AIR-END", "Worn air-end rotors", "high",
                ("loss of capacity", "metallic knocking", "high vibration"),
                {"vibration_rms": 1.6, "discharge_temp": 0.15, "motor_current": 0.12},
                (("P-SCR-0202", 1), ("P-SCR-0204", 2)),
                ("mechanical", "rotating_equipment"), 16.0, needs_workshop=True,
                procedure=("Confirm with a capacity test and vibration spectrum.",
                           "Swap in an exchange compressor if one is available.",
                           "Rebuild the air-end at the workshop; check rotor clearances."),
            ),
            FailureMode(
                "SCR-VLV-INT", "Intake valve sticking", "low",
                ("compressor does not load", "short cycling"),
                {"motor_current": -0.2},
                (("P-SCR-0203", 1),),
                ("mechanical", "controls"), 2.0,
                procedure=("Check the control air signal to the intake valve.",
                           "Clean or replace the intake valve assembly."),
            ),
        ),
    ),
    AssetModel(
        model="CMP-REC-50",
        category="two-stage reciprocating compressor (50 kW)",
        manufacturer="Sierra Compression Works",
        portable=True,
        signals=(
            Signal("discharge_temp", "degC", 140.0, 2.0, warn=165.0, trip=180.0),
            Signal("interstage_pressure", "bar", 2.8, 0.08, warn=3.4, trip=3.8),
            Signal("crankcase_oil_pressure", "bar", 2.5, 0.08, warn=1.6, trip=1.2, low_is_bad=True),
            Signal("vibration_rms", "mm/s", 4.0, 0.4, warn=9.0, trip=14.0),
            Signal("motor_current", "A", 88.0, 2.0, warn=100.0, trip=110.0),
        ),
        parts={
            "P-REC-0301": "Valve plate kit, both stages",
            "P-REC-0302": "Piston ring set",
            "P-REC-0303": "Crankcase oil pump",
            "P-REC-0304": "V-belt set",
            "P-REC-0305": "Cylinder gasket set",
        },
        failure_modes=(
            FailureMode(
                "REC-VLV-WEAR", "Leaking compressor valves", "high",
                ("high discharge temperature", "abnormal interstage pressure", "longer pump-up time"),
                {"interstage_pressure": 0.3, "discharge_temp": 0.2},
                (("P-REC-0301", 1), ("P-REC-0305", 1)),
                ("mechanical",), 4.0,
                procedure=("Compare interstage pressure with the nameplate value at full load.",
                           "Remove the valve covers; inspect valve plates for broken reeds or carbon.",
                           "Fit the valve plate kit with new gaskets; torque per manual."),
            ),
            FailureMode(
                "REC-RING-WEAR", "Worn piston rings", "medium",
                ("oil carryover", "blow-by from crankcase breather", "capacity loss"),
                {"discharge_temp": 0.1, "motor_current": 0.05},
                (("P-REC-0302", 1), ("P-REC-0305", 1)),
                ("mechanical",), 12.0, needs_workshop=True,
                procedure=("Run a pump-up test against the capacity curve.",
                           "Pull the cylinders at the workshop; replace rings and hone the bores."),
            ),
            FailureMode(
                "REC-OIL-PUMP", "Crankcase oil pump failure", "high",
                ("low oil pressure alarm", "knocking from crankcase"),
                {"crankcase_oil_pressure": -0.45},
                (("P-REC-0303", 1),),
                ("mechanical",), 3.0, safety_critical=True,
                procedure=("Stop the unit: running without oil pressure destroys the bearings.",
                           "Check the oil level and pickup screen; replace the oil pump."),
            ),
            FailureMode(
                "REC-BELT", "Slipping drive belts", "low",
                ("belt squeal at start", "slow pump-up", "vibration at the guard"),
                {"vibration_rms": 1.4, "motor_current": -0.1},
                (("P-REC-0304", 1),),
                ("mechanical",), 1.0,
                procedure=("Check belt tension and sheave alignment.",
                           "Replace the belts as a matched set; re-tension after 8 hours."),
            ),
        ),
    ),
    AssetModel(
        model="CMP-CEN-300",
        category="centrifugal compressor (300 kW, 4.16 kV motor)",
        manufacturer="Pacific Turbo Air",
        portable=False,
        signals=(
            Signal("vibration_rms", "mm/s", 2.0, 0.2, warn=4.5, trip=7.1),
            Signal("bearing_temp", "degC", 70.0, 1.5, warn=90.0, trip=100.0),
            Signal("surge_margin_pct", "%", 18.0, 1.0, warn=8.0, trip=4.0, low_is_bad=True),
            Signal("discharge_pressure", "bar", 8.5, 0.15, warn=7.5, trip=7.0, low_is_bad=True),
            Signal("motor_current", "A", 52.0, 1.0, warn=60.0, trip=66.0),
        ),
        parts={
            "P-CEN-0401": "Blow-off valve actuator",
            "P-CEN-0402": "Tilting-pad bearing set",
            "P-CEN-0403": "Inlet filter set",
            "P-CEN-0404": "MV motor terminal and insulation kit",
            "P-CEN-0405": "Turbine oil, 200 L",
        },
        failure_modes=(
            FailureMode(
                "CEN-SURGE", "Surge from a sticking blow-off valve", "high",
                ("surge alarms", "pressure swings", "blow-off valve cycling"),
                {"surge_margin_pct": -0.65},
                (("P-CEN-0401", 1),),
                ("mechanical", "controls"), 4.0,
                procedure=("Review surge events and blow-off valve position in the controller log.",
                           "Stroke-test the blow-off valve; replace the actuator if it lags.",
                           "Re-verify the surge line with the controller's test routine."),
            ),
            FailureMode(
                "CEN-BRG-WEAR", "Bearing wear", "high",
                ("rising vibration", "high bearing temperature", "metal in oil filter"),
                {"vibration_rms": 1.5, "bearing_temp": 0.35},
                (("P-CEN-0402", 1), ("P-CEN-0405", 1)),
                ("mechanical", "rotating_equipment"), 20.0, needs_workshop=True,
                procedure=("Trend vibration and bearing temperature; take an oil sample.",
                           "Open the bearing housings; inspect pads for wiping.",
                           "Replace the bearing set; flush and refill turbine oil."),
            ),
            FailureMode(
                "CEN-IMP-FOUL", "Fouled inlet filters / impeller", "medium",
                ("reduced capacity", "high inlet filter differential"),
                {"discharge_pressure": -0.14, "motor_current": 0.1},
                (("P-CEN-0403", 1),),
                ("mechanical",), 6.0,
                procedure=("Check inlet filter differential pressure.",
                           "Replace the inlet filters; inspect and clean the first-stage impeller."),
            ),
            FailureMode(
                "CEN-MTR-INS", "MV motor insulation breakdown", "critical",
                ("insulation resistance trending down", "partial discharge alarm", "burnt smell at terminal box"),
                {"motor_current": 0.2, "bearing_temp": 0.1},
                (("P-CEN-0404", 1),),
                ("electrical", "hv_certified"), 10.0, safety_critical=True,
                procedure=("De-energize and ground the 4.16 kV feeder per the switching order.",
                           "Megger-test the windings and cables; inspect the terminal box.",
                           "Repair terminations with the insulation kit; HV test before energizing."),
            ),
        ),
    ),
    AssetModel(
        model="CMP-DSL-185",
        category="portable diesel compressor (185 CFM)",
        manufacturer="Mojave Mobile Air",
        portable=True,
        signals=(
            Signal("engine_coolant_temp", "degC", 88.0, 1.0, warn=102.0, trip=108.0),
            Signal("engine_oil_pressure", "bar", 3.8, 0.1, warn=2.2, trip=1.6, low_is_bad=True),
            Signal("discharge_temp", "degC", 95.0, 1.5, warn=115.0, trip=125.0),
            Signal("discharge_pressure", "bar", 7.0, 0.1, warn=6.0, trip=5.5, low_is_bad=True),
        ),
        parts={
            "P-DSL-0501": "Fuel injector",
            "P-DSL-0502": "Radiator hose kit",
            "P-DSL-0503": "Pressure regulator / unloader kit",
            "P-DSL-0504": "Coolant concentrate, 20 L",
        },
        failure_modes=(
            FailureMode(
                "DSL-COOL-LEAK", "Coolant leak / engine overheating", "high",
                ("coolant puddle", "high temperature alarm", "steam from radiator"),
                {"engine_coolant_temp": 0.2},
                (("P-DSL-0502", 1), ("P-DSL-0504", 1)),
                ("diesel", "mechanical"), 3.0, safety_critical=True,
                procedure=("Do not open the radiator cap while hot.",
                           "Pressure-test the cooling system; replace failed hoses.",
                           "Refill and bleed the cooling system."),
            ),
            FailureMode(
                "DSL-INJ", "Fuel injector fault", "medium",
                ("black smoke", "engine hunting", "low air delivery"),
                {"discharge_pressure": -0.16, "engine_coolant_temp": 0.04},
                (("P-DSL-0501", 2),),
                ("diesel",), 4.0,
                procedure=("Run a cylinder cut-out test to find the faulty injector.",
                           "Replace injectors; bleed the fuel system."),
            ),
            FailureMode(
                "DSL-UNLOADER", "Pressure regulator / unloader fault", "low",
                ("pressure does not build", "engine stays at high idle"),
                {"discharge_pressure": -0.12},
                (("P-DSL-0503", 1),),
                ("mechanical", "controls"), 2.0,
                procedure=("Check the regulator setting and control lines for leaks.",
                           "Rebuild the regulator / unloader with the kit."),
            ),
        ),
    ),
    AssetModel(
        model="CMP-SCL-15",
        category="oil-free scroll compressor (15 kW)",
        manufacturer="Coastal Clean Air",
        portable=True,
        signals=(
            Signal("discharge_temp", "degC", 120.0, 1.5, warn=150.0, trip=160.0),
            Signal("dew_point", "degC", 3.0, 0.3, warn=10.0, trip=15.0),
            Signal("vibration_rms", "mm/s", 1.5, 0.15, warn=4.5, trip=7.1),
            Signal("motor_current", "A", 28.0, 0.6, warn=33.0, trip=36.0),
        ),
        parts={
            "P-SCL-0601": "Scroll tip seal kit",
            "P-SCL-0602": "Desiccant dryer cartridge",
            "P-SCL-0603": "Cooling fan motor",
        },
        failure_modes=(
            FailureMode(
                "SCL-TIPSEAL", "Worn scroll tip seals", "medium",
                ("capacity loss", "longer run times", "high discharge temperature"),
                {"discharge_temp": 0.28},
                (("P-SCL-0601", 1),),
                ("mechanical",), 3.0,
                procedure=("Compare run time and capacity against the log.",
                           "Open the scroll element; replace the tip seals."),
            ),
            FailureMode(
                "SCL-DRYER", "Saturated desiccant dryer", "medium",
                ("moisture in air lines", "dew point alarm"),
                {"dew_point": 3.0},
                (("P-SCL-0602", 1),),
                ("mechanical",), 1.0,
                procedure=("Check the dryer purge cycle and dew point sensor.",
                           "Replace the desiccant cartridge."),
            ),
            FailureMode(
                "SCL-FAN", "Cooling fan failure", "medium",
                ("fan not spinning", "high enclosure temperature"),
                {"discharge_temp": 0.3, "motor_current": 0.05},
                (("P-SCL-0603", 1),),
                ("electrical",), 2.0,
                procedure=("Check fan supply voltage and the thermal switch.",
                           "Replace the cooling fan motor."),
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
    "P-SCR-0201": 85, "P-SCR-0202": 6400, "P-SCR-0203": 690, "P-SCR-0204": 310, "P-SCR-0205": 240,
    "P-REC-0301": 520, "P-REC-0302": 980, "P-REC-0303": 640, "P-REC-0304": 120, "P-REC-0305": 90,
    "P-CEN-0401": 2900, "P-CEN-0402": 7800, "P-CEN-0403": 450, "P-CEN-0404": 3600, "P-CEN-0405": 1200,
    "P-DSL-0501": 540, "P-DSL-0502": 160, "P-DSL-0503": 380, "P-DSL-0504": 120,
    "P-SCL-0601": 410, "P-SCL-0602": 260, "P-SCL-0603": 330,
}
