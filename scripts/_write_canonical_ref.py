import json

canonical = {
  "version": "1.0",
  "generated": "2026-03-14",
  "source": "DraftOS archetype library .docx files",
  "note": "Positions marked weight_correction=true had document arithmetic errors (individual weights did not sum to TOTAL=100%). Single minimum Injury adjustment applied.",
  "positions": {
    "QB": {
      "archetypes": 6,
      "archetype_list": ["QB-1 Field General","QB-2 Dual-Threat Architect","QB-3 Gunslinger","QB-4 Game Manager Elevated","QB-5 Raw Projection","QB-6 System-Elevated Starter"],
      "base_weights": {"Processing":28,"SchemeVers":18,"CompTough":14,"DevTraj":12,"Athleticism":10,"Character":8,"Production":6,"Injury":4},
      "weight_sum": 100,
      "bumps": {"QB-1":"Processing->32%","QB-5":"Character->25%","QB-6":"SchemeVers->26%"},
      "gates": ["SAA mandatory before Processing score"]
    },
    "RB": {
      "archetypes": 5,
      "archetype_list": ["RB-1 Elite Workhorse","RB-2 Receiving Specialist","RB-3 Explosive Playmaker","RB-4 Chess Piece","RB-5 Raw Projection"],
      "base_weights": {"Athleticism":20,"Processing":20,"Production":15,"SchemeVers":15,"Injury":7,"CompTough":10,"DevTraj":5,"Character":8},
      "weight_sum": 100,
      "weight_correction": True,
      "note": "Library shows Injury=12% giving sum=105. Adjusted to 7% for sum=100.",
      "bumps": {"RB-1":"Athleticism->25%","RB-3":"Athleticism->25%","RB-4":"Processing->25%, SchemeVers->20%"}
    },
    "WR": {
      "archetypes": 6,
      "archetype_list": ["WR-1 Route Technician","WR-2 Vertical Separator","WR-3 YAC Weapon","WR-4 Contested Catch Specialist","WR-5 Slot Architect","WR-6 Complete Outside Weapon"],
      "note_change": "Was 5 archetypes. WR-3 renamed from YAC Creator. WR-4 renamed from Jump Ball Specialist. WR-5 renamed from Raw Projection. WR-6 is new.",
      "base_weights": {"Processing":22,"Athleticism":18,"Production":16,"SchemeVers":14,"CompTough":12,"Character":8,"DevTraj":6,"Injury":4},
      "weight_sum": 100
    },
    "TE": {
      "archetypes": 5,
      "archetype_list": ["TE-1 Seam Anticipator","TE-2 Mismatch Creator","TE-3 Dual-Threat Complete","TE-4 After-Contact Weapon","TE-5 Raw Projection"],
      "note_change": "TE-3 renamed from Blocking Specialist. TE-4 renamed from Chess Piece.",
      "base_weights": {"Processing":22,"Athleticism":18,"SchemeVers":16,"CompTough":13,"Production":11,"DevTraj":9,"Character":7,"Injury":4},
      "weight_sum": 100,
      "gates": ["PAA gate: scheme-generated target % > 50% caps Production at 6.5/10"]
    },
    "OT": {
      "archetypes": 5,
      "archetype_list": ["OT-1 Elite Athletic Anchor","OT-2 Technician","OT-3 Power Mauler","OT-4 Chess Piece","OT-5 Raw Projection"],
      "note_change": "OT-2 renamed from Zone Technician. OT-3 renamed from Power Road Grader. OT-4 renamed from Developmental Athletic.",
      "base_weights": {"Athleticism":25,"Processing":20,"CompTough":16,"SchemeVers":14,"Injury":12,"DevTraj":8,"Production":5,"Character":"Var(0-12)"},
      "weight_sum": 100,
      "weight_correction": True,
      "note": "Library shows CompTough=18% giving sum=102 (without Var. Character). Adjusted CompTough to 16% for sum=100.",
      "bumps": {"OT-3":"Athleticism->20%","OT-5":"DevTraj->15%, Character->12%"}
    },
    "OG": {
      "archetypes": 5,
      "archetype_list": ["OG-1 Complete Interior Anchor","OG-2 Mauler","OG-3 Athletic Zone Mauler","OG-4 Technician","OG-5 Versatile Chess Piece"],
      "note_change": "OG-3 renamed from Zone Puller. OG-4 renamed from Chess Piece. OG-5 renamed from Raw Projection. C position now separate.",
      "base_weights": {"CompTough":22,"Processing":20,"Athleticism":15,"SchemeVers":14,"Injury":12,"DevTraj":9,"Production":5,"Character":3},
      "weight_sum": 100,
      "bumps": {"OG-1":"Processing->24%","OG-3":"Athleticism->20%","OG-5":"DevTraj->15%"}
    },
    "C": {
      "archetypes": 6,
      "archetype_list": ["C-1 Cerebral Anchor","C-2 Complete Interior Presence","C-3 Power Anchor","C-4 Zone Technician","C-5 Projection Athlete","C-6 Guard Convert"],
      "note": "New separate section. Was previously collapsed into OG. Library uses OC- prefix; prompts.py uses C-.",
      "base_weights": {"Processing":28,"Athleticism":18,"SchemeVers":14,"CompTough":12,"Character":10,"DevTraj":8,"Production":6,"Injury":4},
      "weight_sum": 100
    },
    "EDGE": {
      "archetypes": 5,
      "archetype_list": ["EDGE-1 Every-Down Disruptor","EDGE-2 Speed-Bend Specialist","EDGE-3 Power-Counter Technician","EDGE-4 Athletic Dominator","EDGE-5 Hybrid Tweener Rusher"],
      "note_change": "EDGE-2 renamed from Speed Rusher. EDGE-3 renamed from Technician. EDGE-4 renamed from Toolbox.",
      "base_weights": {"Processing":20,"Athleticism":18,"CompTough":14,"SchemeVers":13,"DevTraj":12,"Production":11,"Injury":7,"Character":5},
      "weight_sum": 100,
      "bumps": {"EDGE-1":"CompTough->16%","EDGE-2":"Athleticism->22%","EDGE-3":"DevTraj->15%","EDGE-4":"Processing->16%","EDGE-5":"SchemeVers->18%"}
    },
    "IDL": {
      "archetypes": 5,
      "archetype_list": ["DT-1 Interior Wrecker","DT-2 Versatile Disruptor","DT-3 Two-Gap Anchor","DT-4 Hybrid Penetrator-Anchor","DT-5 Pass Rush Specialist"],
      "note_change": "DT-2 renamed from Two-Gap Anchor. DT-3 renamed from Scheme Fit. DT-4 renamed from Nose Tackle. DT-5 renamed from Raw Projection.",
      "table_a_weights": {"Athleticism":22,"Processing":20,"CompTough":16,"Production":14,"SchemeVers":12,"DevTraj":8,"Injury":5,"Character":3},
      "table_b_weights": {"CompTough":24,"Athleticism":18,"Processing":16,"SchemeVers":15,"Production":13,"Injury":8,"DevTraj":4,"Character":2},
      "weight_sum_a": 100,
      "weight_sum_b": 100
    },
    "ILB": {
      "archetypes": 5,
      "archetype_list": ["ILB-1 Green Dot Anchor","ILB-2 Coverage Eraser","ILB-3 Run-First Enforcer","ILB-4 Hybrid Chess Piece","ILB-5 Raw Projection"],
      "note_change": "ILB-3 renamed from Pressure Converter. ILB-4 renamed from Raw Projection. ILB-5 is new.",
      "base_weights": {"Processing":25,"Athleticism":15,"SchemeVers":15,"CompTough":13,"Character":12,"DevTraj":10,"Production":8,"Injury":2},
      "weight_sum": 100,
      "weight_correction": True,
      "note": "Library shows Injury=7% giving sum=105. Adjusted to 2% for sum=100."
    },
    "OLB": {
      "archetypes": 5,
      "archetype_list": ["OLB-1 Speed-Bend Specialist","OLB-2 Hand Fighter / Counter Rusher","OLB-3 Hybrid Pass Rush / Coverage Dropper","OLB-4 Power Bull / Run Defender First","OLB-5 Raw Projection / Developmental Rusher"],
      "note": "New separate section. Was previously collapsed into ILB.",
      "base_weights": {"Athleticism":22,"Processing":20,"SchemeVers":18,"CompTough":13,"Production":12,"Character":8,"DevTraj":5,"Injury":2},
      "weight_sum": 100,
      "weight_correction": True,
      "note_correction": "Library shows Injury=5% giving sum=103. Adjusted to 2% for sum=100."
    },
    "CB": {
      "archetypes": 5,
      "archetype_list": ["CB-1 Anticipatory Lockdown","CB-2 Zone Architect","CB-3 Press Man Corner","CB-4 Slot Specialist","CB-5 Raw Projection"],
      "note": "Archetype names kept from current prompts.py (canonical). Library summary table uses different short names; these are authoritative per audit.",
      "base_weights": {"Processing":22,"Athleticism":20,"SchemeVers":16,"CompTough":14,"DevTraj":10,"Character":8,"Production":7,"Injury":3},
      "weight_sum": 100,
      "weight_correction": True,
      "note_correction": "Library shows Injury=7% giving sum=104. Adjusted to 3% for sum=100.",
      "bumps": {"CB-1":"Processing->28%","CB-3":"Athleticism->26%"}
    },
    "S": {
      "archetypes": 5,
      "archetype_list": ["S-1 Centerfielder","S-2 Box Enforcer","S-3 Multiplier Safety","S-4 Coverage Safety","S-5 Raw Projection"],
      "note_change": "S-3 renamed from Versatile Weapon. S-4 Coverage Safety is new. S-5 Raw Projection was S-4.",
      "base_weights": {"Processing":25,"Athleticism":18,"SchemeVers":15,"CompTough":13,"Character":10,"DevTraj":9,"Production":6,"Injury":4},
      "weight_sum": 100,
      "gates": ["SOS gate: majority of coverage reps vs top-50 required; otherwise cap Eval Confidence at Tier B"]
    }
  }
}

out_path = r"C:\DraftOS\draftos\docs\apex\archetype_canonical_reference.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(canonical, f, indent=2, ensure_ascii=False)
print(f"Saved: {out_path}")
