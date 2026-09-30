"""
Generates the eval set: synthetic lab reports with ground-truth severity.

Why synthetic: there is no real patient data here, and the point of the eval
harness is to measure the model against a known-correct answer. Every report is
built from a clinical template whose values are chosen to sit unambiguously on
one side of the severity rules in llm.SYSTEM_PROMPT, so the label is
defensible rather than opinion.

Run:  python -m eval.make_dataset
Then:  python -m eval.run_eval

The noise axis is the important part. Real referrals arrive as phone photos of
photocopied reports, so the same clinical picture appears with dropped
characters, inconsistent units, hand-written abbreviations and missing lines.
A model that only works on clean text is not usable here, and a harness with no
noise would hide that.
"""

import json
import os
import random

OUT = os.path.join(os.path.dirname(__file__), "lab_reports.json")

NAMES = [
    "Ravi Kumar", "Sunita Devi", "Mohammed Irfan", "Lakshmi Narayan", "Anjali Verma",
    "Suresh Babu", "Priya Menon", "Rajesh Yadav", "Fatima Sheikh", "Gopal Das",
    "Meena Kumari", "Arun Pillai", "Zoya Khan", "Deepak Sharma", "Kavita Rao",
    "Imran Qureshi", "Sita Devi", "Naveen Gowda", "Rekha Patil", "Vikram Singh",
]

# Each template: (id_suffix, severity, specialist, clinical_body, note)
# Values are chosen to match the severity rules exactly, so the expected label
# follows from the published criteria rather than from a human's judgement call.
TEMPLATES = [
    # ---------------- Green ----------------
    ("routine_fever", "Green", "none", """
    Name: {name}   Age: 34 yrs   Sex: M
    Presenting complaint: Fever 3 days, body ache, no rash.
    Temp 100.2 F, PR 88/min, BP 120/80 mmHg, SpO2 98% on room air.
    WBC 9,800/cumm, Hb 14.2 g/dL, Platelets 2.4 lakh/uL
    RFT: Urea 22 mg/dL, Creatinine 0.9 mg/dL
    Dengue NS1 antigen: Negative
    MAL parasite: Negative
    Physician note: Stable vitals. Likely viral fever. Oral fluids and
    paracetamol advised. No admission required.
    """, "normal platelets, stable vitals"),

    ("viral_pharyngitis", "Green", "none", """
    {name}, 27/F. Sore throat, mild fever 99.5 F since 2 days.
    BP 118/76, HR 82, RR 18, SpO2 99%.
    CBC: Hb 13.1, TLC 7,200, Platelets 3.1 lakh
    No investigations otherwise indicated.
    Advised: paracetamol 500mg SOS, warm gargles, review if not improving.
    """, "no abnormal values"),

    ("mild_anemia", "Green", "none", """
    Name {name}, 41 yrs F. Complaining of mild weakness and hair loss.
    P/S: afebrile, stable, BMI normal.
    Hb 11.8 g/dL, TLC 6,900, Platelets 2.8 lakh
    Serum ferritin 18 ng/mL (low)
    Stool for occult blood: Negative
    Advice: oral iron, review in 2 weeks as outpatient.
    """, "Hb >11 g/dL = mild anaemia, outpatient"),

    ("stable_postop_check", "Green", "none", """
    {name}, 52/M. Post-op day 2 after elective inguinal hernia repair.
    Afebrile, wound clean and dry, no discharge.
    PR 80, BP 130/85, SpO2 98%, chest clear.
    Hb 13.6, TLC 10,200, Platelets 2.5 lakh, Urea 26, Creat 1.0
    Discharged with oral paracetamol and a follow-up date.
    """, "routine post-op, no red flags"),

    # ---------------- Yellow ----------------
    ("moderate_dengue", "Yellow", "hematologist", """
    Name: {name}, 29 yrs M, Rampur.
    C/O: Fever 5 days, severe body pain, mild abdominal discomfort.
    Temp 101.4 F, PR 104/min, BP 108/72, SpO2 97%.
    Platelets 42,000/uL
    WBC 6,100, Hb 13.0, Haematocrit 44%
    Dengue NS1: POSITIVE
    LFT: AST 68, ALT 74 U/L (mildly elevated)
    No bleeding, no plasma leak. Not in shock.
    Plan: admit for observation, oral rehydration, paracetamol.
    """, "platelets 42k = moderate, no shock"),

    ("pneumonia", "Yellow", "none", """
    {name}, 61/M. Productive cough with yellow sputum, fever 5 days,
    chest pain on breathing.
    Temp 102 F, RR 26/min, HR 104, BP 126/80, SpO2 93% on room air.
    Chest X-ray: patchy consolidation in right lower zone.
    CBC: Hb 12.4, TLC 15,800, Platelets 2.2 lakh
    CRP 96 mg/L. Blood culture sent.
    Plan: IV ceftriaxone, admit to ward, oxygen as needed.
    """, "hypoxaemia + consolidation, stable"),

    ("dehydration_gastroenteritis", "Yellow", "none", """
    {name}, 24/M. Loose motions 6 times, vomiting 3 times, poor intake.
    Sunken eyes, dry tongue, skin pinch slow.
    Temp 99.8 F, HR 112/min, BP 96/62, SpO2 98%.
    Na 132, K 3.1, Serum creatinine 1.2 mg/dL, Urea 38
    CBC: Hb 15.1, TLC 12,600, Platelets 3.4 lakh
    Plan: ORS, IV ringer lactate if unable to tolerate oral.
    """, "moderate dehydration, perfusion borderline"),

    ("moderate_anemia", "Yellow", "none", """
    {name}, 38/F. Puerperal woman, 3 weeks post-delivery. Complaining of
    weakness, giddiness on standing.
    P/S: pale, tachycardic HR 108, BP 104/68, SpO2 97%, no jaundice.
    Hb 8.6 g/dL, TLC 8,900, Platelets 2.6 lakh
    MCV 68 fL, Serum ferritin 9 ng/mL
    Plan: admit, parenteral iron, investigate for bleeding source.
    """, "Hb 8.6 g/dL = moderate anaemia, symptomatic"),

    # ---------------- Red ----------------
    ("severe_dengue", "Red", "hematologist", """
    Name: {name}, 26 yrs M.
    C/O: Fever 7 days, vomiting, severe abdominal pain, bleeding from gums.
    Temp 101 F, HR 124/min, BP 88/58 mmHg, pulse pressure narrow (30),
    SpO2 95%. Cold clammy extremities, cap refill 4 sec.
    Platelets 9,800/uL
    Haematocrit 52% (rose from 41% on day 3)
    WBC 3,200, Hb 14.8
    Dengue NS1: POSITIVE
    Tourniquet test: strongly positive, petechiae on both legs
    FAST scan: free fluid in abdomen
    Impression: Dengue haemorrhagic fever with shock. Plasma leak.
    Plan: admit to ICU, IV ringer lactate, blood products, platelets.
    """, "platelets 9.8k + haemoconcentration + shock = Red"),

    ("acute_coronary_syndrome", "Red", "cardiologist", """
    {name}, 58/M. Severe crushing chest pain radiating to left arm,
    onset 1 hour ago, associated diaphoresis.
    BP 96/58, HR 104, RR 22, SpO2 94%.
    ECG: ST elevation in V1-V4, reciprocal changes inferior.
    Troponin I 6.8 ng/mL, CK-MB elevated
    Hb 13.9, Platelets 2.6 lakh, Creatinine 1.1
    Plan: immediate thrombolysis with streptokinase, aspirin 150mg,
    admit to CCU, monitored bed.
    """, "STEMI = Red"),

    ("severe_anemia", "Red", "hematologist", """
    Name {name}, 22 yrs F, known heavy menstrual bleeding.
    Complains of severe weakness, breathlessness at rest, palpitations.
    P/S: very pale, HR 128/min, BP 82/54, SpO2 92%, flow-sheet murmur.
    Hb 6.2 g/dL
    TLC 11,200, Platelets 3.6 lakh, MCV 59 fL
    Reticulocytes 0.8%
    Plan: admit, cross-match 2 units, transfuse, ICU bed.
    """, "Hb 6.2 g/dL + heart failure = Red"),

    ("stroke", "Red", "none", """
    {name}, 70/M, known hypertensive.
    Found unconscious at home 2 hours back by family.
    GCS 9/15 (E2 V2 M5), right-sided hemiparesis, slurred speech.
    BP 186/102, HR 88, SpO2 96%.
    CT brain: no haemorrhage, left MCA territory infarct.
    Platelets 2.4 lakh, Hb 13.2, RBS 148, Creat 1.0
    Plan: admit to ICU for thrombolysis window monitoring, aspirin,
    stroke unit referral.
    """, "GCS 9 = Red"),

    ("sepsis", "Red", "none", """
    {name}, 63/M, known type 2 diabetes.
    Fever with chills 4 days, reduced urine output, confusion since morning.
    Temp 104.8 F, HR 138/min, BP 78/46 mmHg, RR 32, SpO2 90% on 4L O2.
    Cap refill 5 sec, mottled extremities, oliguria.
    Lactate 5.2 mmol/L
    TLC 24,600, Hb 12.1, Platelets 78,000/uL, Creatinine 2.8 mg/dL
    Urine: nitrite positive, pus cells abundant
    Blood culture: growth of E. coli (preliminary)
    Impression: Septic shock secondary to complicated UTI.
    Plan: ICU, broad-spectrum IV antibiotics, aggressive fluids, vasopressors.
    """, "lactate 5.2 + hypotension = septic shock = Red"),

    ("paediatric_severe_anaemia", "Red", "pediatrician", """
    Name {name}, 3 yrs, weight 11 kg. Mother reports poor appetite and
    lethargy since 2 weeks. Refusal of feeds.
    HR 146/min, RR 40/min, temp 99.4 F, pallor+++, oedema present.
    Hb 5.4 g/dL, TLC 18,200, Platelets 3.9 lakh
    PCV 17%, MCV 54 fL
    Plan: admit to paediatric ward, admit to ICU, blood transfusion,
    deworming, nutritional rehabilitation.
    """, "Hb 5.4 in a 3-year-old = Red"),

    ("severe_pneumonia_with_sepsis", "Red", "pediatrician", """
    {name}, 2 yrs 8 months, 11 kg.
    Fast breathing since 2 days, grunting, cannot feed, convulsions at home.
    RR 54/min, HR 158/min, temp 105 F, SpO2 88% on oxygen, grunting,
    chest indrawing, crackles bilateral.
    GCS 12/15, capillary refill 5 sec.
    WBC 22,000, Hb 9.8, Platelets 4.2 lakh
    CXR: bilateral perihilar infiltrates
    Plan: ICU admission, IV ceftriaxone, nebulisation, oxygen, ceftazidime.
    """, "hypoxaemia + shock + convulsion in child = Red"),

    # ---------------- unreadable / adversarial ----------------
    ("illegible_scan", "Yellow", "none", """
    [SCAN UNCLEAR - MULTIPLE PAGES]
    ....... pltslts: ~~~~~
    Hb: ? mg/dl
    Physician note: send again
    """, "insufficient data - must not be auto-cleared Green"),

    ("incomplete_upload", "Yellow", "none", """
    Patient name: {name}
    Sent from CHC.
    "platelets low, please advise" - ANO
    """, "one ambiguous sentence, no values"),

    # ---------------- adversarial ----------------
    # These are the cases a keyword matcher structurally cannot get right. They
    # exist to test whether the model is reading values or pattern-matching
    # words - the negation cases in particular are why we use a model at all.
    ("negated_shock_mention", "Yellow", "hematologist", """
    Name: {name}, 34 yrs M. Admitted with dengue fever, day 5.
    Attended by medical registrar.
    Temp 100.8 F, HR 96/min, BP 116/74, SpO2 98%.
    Platelets 68,000/uL, WBC 5,200, Haematocrit 39%
    Dengue NS1 POSITIVE.
    Examination: no shock, no bleeding, no plasma leak, no pleural effusion.
    Clinician note: patient is NOT in shock and is haemodynamically stable.
    No need for blood products. Plan: continue oral rehydration on the ward,
    monitor platelets daily, review in 48 hours.
    """, "stable, no shock - text contains 'shock' only as negation"),

    ("negated_bleeding", "Yellow", "hematologist", """
    {name}, 45/F, dengue day 6.
    Temp 100.4 F, HR 88, BP 124/78, SpO2 99%.
    Platelets 74,000/uL, Haematocrit 40%, WBC 6,800
    No bleeding from gums or petechiae. Tourniquet test negative.
    No plasma leak on ultrasound. Not for ICU, no transfusion needed.
    Plan: ward observation, ORS, paracetamol.
    """, "negated bleeding/shock language, still thrombocytopenic"),

    ("unit_confusion_lakh", "Yellow", "hematologist", """
    {name}, 31 yrs M. Dengue.
    Reported by referring centre in lakh/uL notation:
    TLC 8.2,000  Hb 13.4  Platelets 0.74 lakh  Haematocrit 41%
    Vitals stable, afebrile since morning, passing urine adequately.
    Dengue NS1 positive.
    Clinician note: 0.74 lakh/uL is approximately 74,000/uL, which is
    moderate thrombocytopenia and does not need platelet transfusion.
    Plan: admit for observation.
    """, "platelets written as 0.74 lakh, needs unit normalisation"),

    ("stable_but_mentions_icu", "Green", "none", """
    {name}, 28/M, dengue day 3.
    Temp 99.6 F, HR 84, BP 122/78, SpO2 98%, capillary refill 2 sec.
    Platelets 1.8 lakh, WBC 7,200, Hb 14.1
    Dengue NS1 positive. No warning signs. Drinking orally.
    Physician note: if platelets fall below 1 lakh or he develops warning
    signs, escalate to ICU. Currently for ward-based care, no ICU needed.
    Discharged today with oral rehydration salts.
    """, "ICU appears only in a conditional plan line; patient is Green"),

    ("borderline_platelets", "Yellow", "hematologist", """
    {name}, 19 yrs F, dengue day 5.
    Temp 101 F, HR 92, BP 112/70, SpO2 98%.
    Platelets 21,000/uL
    WBC 4,900, Haematocrit 39%, Hb 12.8
    Dengue NS1 positive.
    No bleeding, no plasma leak, haemodynamically stable.
    Physician note: just above the 20,000 transfusion threshold; admit for
    close monitoring rather than transfuse.
    """, "platelets 21k, borderline - moderate not severe"),

    ("paediatric_narrative_only", "Yellow", "pediatrician", """
    Patient: {name}, age 5 years, weight 18 kg. Brought by mother.
    Mother reports the child has had fever for 4 days and is eating very
    little. Mother also mentions the child is 'very weak and drowsy'.
    On examination the child is alert and responds to mother, drinks some
    water, breathing is normal, no grunting, no convulsion in the last 24 hrs.
    Treating doctor could not get blood drawn today.
    Advised: ORS sips, paracetamol half tablet, review tomorrow morning.
    """, "child, weak but no red flags, key values missing"),

    ("missed_icu_patient", "Red", "none", """
    {name}, 57/M, diabetic, presented with fever and altered sensorium.
    On arrival HR 132, BP 84/52, SpO2 90% on 2L, cap refill 5 sec, mottled.
    Cold extremities, oliguria since morning.
    Serum lactate 4.9 mmol/L. Urine culture: E. coli.
    TLC 19,800, Platelets 92,000/uL, Creatinine 2.4 mg/dL.
    Physician note: needs admission to the intensive care unit for
    inotropes and broad spectrum antibiotics.
    """, "septic shock - lactate 4.9 + hypotension"),
]

# Additive corruption to simulate OCR of a photocopied referral slip.
OCR_SUBSTITUTIONS = [
    ("Platelets", "Platelets"), ("platelets", "platclets"), ("Hemoglobin", "Haemoglobin"),
    ("Hb", "Hb"), ("WBC", "WBC"), ("TLC", "T1C"), ("Creatinine", "Creatininc"),
    ("SpO2", "Sp02"), ("mg/dL", "mg/dL"), ("Temperature", "Temp"),
]


def _corrupt(text: str, rng: random.Random) -> str:
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
    out = []
    for ln in lines:
        # Swap a random digit pair on numeric-bearing lines - the single most
        # common real OCR error and the one most likely to change severity.
        if any(ch.isdigit() for ch in ln) and rng.random() < 0.28:
            chars = list(ln)
            idxs = [i for i, c in enumerate(chars) if c.isdigit()]
            if len(idxs) >= 2:
                a, b = rng.sample(idxs, 2)
                chars[a], chars[b] = chars[b], chars[a]
                ln = "".join(chars)
        if rng.random() < 0.18:
            for good, bad in OCR_SUBSTITUTIONS:
                if good in ln:
                    ln = ln.replace(good, bad, 1)
                    break
        if rng.random() < 0.10:
            ln = ln.replace("  ", " ").strip()
        out.append(ln)
    return "\n".join(out)


def build(count_per_template: int = 2) -> list:
    rng = random.Random(20240917)
    reports = []
    idx = 0
    for tpl, severity, specialist, body, note in TEMPLATES:
        for rep in range(count_per_template):
            idx += 1
            name = rng.choice(NAMES)
            text = body.format(name=name)
            # Keep a clean copy and an OCR-degraded copy of every template so
            # the harness can report accuracy for each noise level separately.
            reports.append({
                "id": f"r{idx:03d}",
                "template": tpl,
                "expected_severity": severity,
                "expected_specialist": specialist,
                "note": note,
                "noise": "clean",
                "report_text": text.strip(),
            })
            if severity != "Yellow" or tpl.startswith(("illegible", "incomplete")):
                reports.append({
                    "id": f"r{idx:03d}n",
                    "template": tpl,
                    "expected_severity": severity,
                    "expected_specialist": specialist,
                    "note": note,
                    "noise": "ocr",
                    "report_text": _corrupt(text, rng),
                })
    return reports


def main():
    reports = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)

    from collections import Counter
    sev = Counter(r["expected_severity"] for r in reports)
    noise = Counter(r["noise"] for r in reports)
    print(f"wrote {len(reports)} reports -> {OUT}")
    print("severity:", dict(sev))
    print("noise:    ", dict(noise))
    print("templates:", len(TEMPLATES))


if __name__ == "__main__":
    main()
