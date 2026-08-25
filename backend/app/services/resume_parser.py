import pdfplumber
import re
import spacy

from app.services.embedding_service import generate_embedding

nlp = spacy.load("en_core_web_sm")


# ---------------- PDF TEXT EXTRACTION ----------------

def extract_text(pdf_path):
    text = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    return text


# ---------------- EMAIL ----------------

def extract_email(text):

    match = re.search(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text
    )

    return match.group(0) if match else None


# ---------------- PHONE ----------------

def extract_phone(text):

    match = re.search(
        r"(\+?\d[\d\s\-]{8,}\d)",
        text
    )

    return match.group(0) if match else None


# ---------------- NAME ----------------

def extract_name(text):

    lines = text.split("\n")

    for line in lines[:8]:

        line = line.strip()

        if not line:
            continue

        if "@" in line:
            continue

        if any(char.isdigit() for char in line):
            continue

        if len(line.split()) < 2:
            continue

        if len(line.split()) > 4:
            continue

        if line.isupper():
            return line.title()

        return line

    doc = nlp(text)

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text

    return None


# ---------------- SKILLS (profession-agnostic) ----------------
#
# NOTE: TalentNest must not assume the candidate is any particular
# profession (developer, teacher, nurse, driver, etc.), so skills are
# NEVER matched against a fixed hard-coded vocabulary here. A CS-only
# skill dictionary would silently make every non-technical resume look
# "skill-less". Instead this is a generic, structure-based extractor:
# it finds whatever section(s) of the resume the candidate themselves
# labeled as skills/competencies/tools/qualifications and reads the
# items out of that section, regardless of what profession they are.
#
# This is a lightweight, offline fallback only. The authoritative,
# evidence-grounded extraction (which also works for requirements that
# don't appear under a "Skills" heading at all) happens in the AI
# recruiter analysis (see app/services/ollama_service.py).

SKILL_SECTION_HEADERS = re.compile(
    r"^\s*(technical\s+skills|core\s+skills|key\s+skills|skills\s*(?:&|and)?\s*"
    r"competencies|core\s+competencies|areas?\s+of\s+expertise|competencies|"
    r"qualifications|tools\s*(?:&|and)?\s*technologies|equipment|"
    r"certifications?|licenses?|skills)\s*:?\s*$",
    re.IGNORECASE,
)

# Any of these starting a later line signals the skills section has ended.
SECTION_STOP_HEADERS = re.compile(
    r"^\s*(experience|work\s+experience|employment|education|projects|"
    r"certifications?|licenses?|languages?|references|summary|objective|"
    r"achievements|awards|responsibilities|profile)\s*:?\s*$",
    re.IGNORECASE,
)


def extract_skills(text):
    """
    Extract skill/competency-like items from whichever section of the
    resume the candidate labeled that way, without assuming any
    profession. Works the same for a developer's "Technical Skills"
    section, a teacher's "Core Competencies" section, a driver's
    "Licenses" section, or a chef's "Skills" section.
    """

    lines = text.split("\n")
    collected = []
    in_section = False

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            continue

        if SKILL_SECTION_HEADERS.match(line):
            in_section = True
            continue

        if in_section:
            if SECTION_STOP_HEADERS.match(line):
                in_section = False
                continue

            # Skills sections are typically comma/pipe/bullet separated,
            # or one item per line - split on the common separators and
            # keep short, label-like fragments (not full sentences).
            fragments = re.split(r"[,|•·;/]| - ", line)
            for frag in fragments:
                item = frag.strip(" \t-•*").strip()
                if item and 1 <= len(item.split()) <= 6 and len(item) <= 60:
                    collected.append(item)

    # De-duplicate while preserving order and original casing.
    seen = set()
    result = []
    for item in collected:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result


# ---------------- MAIN PARSER ----------------

def parse_resume(pdf_path):

    text = extract_text(pdf_path)

    embedding = generate_embedding(text)

    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "skills": extract_skills(text),
        "raw_text": text,
        "embedding": embedding
    }