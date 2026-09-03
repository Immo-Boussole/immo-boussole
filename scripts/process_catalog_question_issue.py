#!/usr/bin/env python3
"""
Script to parse a GitHub Issue Form proposing an addition, modification,
deletion, or translation of a standard question, and update app/data/default_catalog_questions.json.
"""
from __future__ import annotations
import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

JSON_PATH = Path(__file__).parent.parent / "app" / "data" / "default_catalog_questions.json"


def extract_field(issue_body: str, field_pattern: str) -> str:
    """
    Extracts the content below an issue form section header (### Header).
    """
    pattern = rf"###\s*{field_pattern}.*?\n+([^\n#]+(?:\n+(?![#]).*)*)"
    match = re.search(pattern, issue_body, re.IGNORECASE)
    if match:
        val = match.group(1).strip()
        if val.lower() in ("_no response_", "none", "n/a", "na", "aucun", "non renseigné"):
            return ""
        return val
    return ""


def clean_language(raw_lang: str) -> str:
    if not raw_lang:
        return "fr"
    raw_lower = raw_lang.strip().lower()
    # Extract ISO code inside parenthesis or before
    code_match = re.match(r"^([a-z]{2,3})\b", raw_lower)
    if code_match:
        return code_match.group(1)
    if "fr" in raw_lower:
        return "fr"
    if "en" in raw_lower:
        return "en"
    if "es" in raw_lower:
        return "es"
    if "de" in raw_lower:
        return "de"
    if "it" in raw_lower:
        return "it"
    if "pt" in raw_lower:
        return "pt"
    if "nl" in raw_lower:
        return "nl"
    return raw_lower[:10]


def clean_category(raw_cat: str) -> str:
    if not raw_cat:
        return "Inspection technique"
    # If formatted as "Structure & Gros œuvre / Structure & Shell", keep clean name
    clean = raw_cat.split("/")[0].strip()
    return clean or "Inspection technique"


def clean_themes(raw_themes: str) -> List[str]:
    if not raw_themes:
        return ["Général"]
    items = [t.strip() for t in raw_themes.replace(";", ",").split(",") if t.strip()]
    return items or ["Général"]


def parse_issue_form(issue_body: str) -> Dict[str, Any]:
    """
    Parses all relevant fields from the GitHub Issue Form markdown body.
    """
    raw_action = extract_field(issue_body, r"Action\s*/")
    raw_language = extract_field(issue_body, r"Language\s*/")
    raw_category = extract_field(issue_body, r"Category\s*/")
    raw_themes = extract_field(issue_body, r"Themes\s*/")
    raw_q_text = extract_field(issue_body, r"Proposed Question Text\s*/")
    raw_target_text = extract_field(issue_body, r"Target Existing Question\s*/")
    raw_advice = extract_field(issue_body, r"Verification Advice\s*/")
    raw_justification = extract_field(issue_body, r"Motivation\s*/")

    action_lower = raw_action.lower()
    if "ajout" in action_lower or "add" in action_lower:
        action = "add"
    elif "modif" in action_lower or "update" in action_lower:
        action = "modify"
    elif "suppr" in action_lower or "remove" in action_lower or "delete" in action_lower:
        action = "remove"
    elif "trad" in action_lower or "translat" in action_lower:
        action = "translate"
    else:
        action = "add"

    return {
        "action": action,
        "language": clean_language(raw_language),
        "category": clean_category(raw_category),
        "themes": clean_themes(raw_themes),
        "question_text": raw_q_text.strip(),
        "target_existing_text": raw_target_text.strip(),
        "advice_notes": raw_advice.strip() or None,
        "justification": raw_justification.strip() or None,
    }


def load_questions() -> List[Dict[str, Any]]:
    if JSON_PATH.is_file():
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_questions(questions: List[Dict[str, Any]]) -> None:
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
        f.write("\n")


def find_matching_question(
    questions: List[Dict[str, Any]],
    query_text: str,
    language: Optional[str] = None
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    Finds a question by ID or fuzzy text match.
    """
    clean_query = query_text.strip().lower()
    if not clean_query:
        return None

    # Check if query is numeric ID
    if clean_query.isdigit():
        target_id = int(clean_query)
        for idx, q in enumerate(questions):
            if q.get("id") == target_id:
                return idx, q

    # Match by exact text and language
    for idx, q in enumerate(questions):
        q_text = (q.get("question_text") or "").strip().lower()
        q_lang = (q.get("language") or "fr").strip().lower()
        if q_text == clean_query:
            if language is None or q_lang == language.lower():
                return idx, q

    # Match by text containment
    for idx, q in enumerate(questions):
        q_text = (q.get("question_text") or "").strip().lower()
        if clean_query in q_text or q_text in clean_query:
            if language is None or (q.get("language") or "fr").lower() == language.lower():
                return idx, q

    return None


def process_catalog_issue(issue_body: str) -> Dict[str, Any]:
    """
    Processes the parsed issue and applies the mutation to default_catalog_questions.json.
    Returns a result dict with success status, action, and human-readable PR summary.
    """
    parsed = parse_issue_form(issue_body)
    action = parsed["action"]
    q_text = parsed["question_text"]
    target_text = parsed["target_existing_text"]
    lang = parsed["language"]
    cat = parsed["category"]
    themes = parsed["themes"]
    advice = parsed["advice_notes"]
    justification = parsed["justification"]

    questions = load_questions()
    result = {
        "success": False,
        "action": action,
        "language": lang,
        "question_text": q_text,
        "commit_title": "",
        "pr_title": "",
        "pr_summary": "",
        "error": None
    }

    if not q_text and action != "remove":
        result["error"] = "Le texte de la question est obligatoire / Question text is required."
        return result

    if action == "add":
        # Check duplicate in same language
        for q in questions:
            if (q.get("question_text") or "").strip().lower() == q_text.lower() and (q.get("language") or "fr").lower() == lang.lower():
                result["error"] = f"La question existe déjà pour la langue '{lang}' / Question already exists."
                return result

        next_id = max([q.get("id", 0) for q in questions], default=0) + 1
        new_entry = {
            "id": next_id,
            "question_text": q_text,
            "themes": themes,
            "category": cat,
            "advice_notes": advice,
            "language": lang
        }
        questions.append(new_entry)
        save_questions(questions)

        result["success"] = True
        result["commit_title"] = f"feat(catalog): add question ({lang}) - {q_text[:50]}"
        result["pr_title"] = f"feat(catalog): add inspection question [{lang.upper()}]"
        result["pr_summary"] = (
            f"### ➕ New Inspection Question Added\n\n"
            f"- **Language**: `{lang}`\n"
            f"- **Category**: {cat}\n"
            f"- **Themes**: {', '.join(themes)}\n"
            f"- **Question**: {q_text}\n"
            f"- **Advice Notes**: {advice or '_None_'}\n\n"
            f"**Motivation**: {justification or '_Not provided_'}"
        )

    elif action == "modify":
        lookup_query = target_text or q_text
        match = find_matching_question(questions, lookup_query, language=lang)
        if not match:
            # Try finding without strict language filter
            match = find_matching_question(questions, lookup_query)

        if not match:
            result["error"] = f"Question cible non trouvée pour modification: '{lookup_query}'."
            return result

        idx, target_q = match
        old_text = target_q["question_text"]
        target_q["question_text"] = q_text
        target_q["category"] = cat
        target_q["themes"] = themes
        target_q["language"] = lang
        if advice is not None:
            target_q["advice_notes"] = advice

        save_questions(questions)
        result["success"] = True
        result["commit_title"] = f"fix(catalog): update question #{target_q.get('id')} ({lang})"
        result["pr_title"] = f"fix(catalog): update question #{target_q.get('id')} [{lang.upper()}]"
        result["pr_summary"] = (
            f"### ✏️ Inspection Question Modified\n\n"
            f"- **Question ID**: `#{target_q.get('id')}`\n"
            f"- **Language**: `{lang}`\n"
            f"- **Original Text**: {old_text}\n"
            f"- **Updated Text**: {q_text}\n"
            f"- **Category**: {cat}\n"
            f"- **Themes**: {', '.join(themes)}\n"
            f"- **Advice Notes**: {advice or '_None_'}\n\n"
            f"**Motivation**: {justification or '_Not provided_'}"
        )

    elif action == "remove":
        lookup_query = target_text or q_text
        match = find_matching_question(questions, lookup_query, language=lang)
        if not match:
            match = find_matching_question(questions, lookup_query)

        if not match:
            result["error"] = f"Question cible non trouvée pour suppression: '{lookup_query}'."
            return result

        idx, target_q = match
        deleted_item = questions.pop(idx)
        save_questions(questions)

        result["success"] = True
        result["commit_title"] = f"refactor(catalog): remove question #{deleted_item.get('id')} ({deleted_item.get('language')})"
        result["pr_title"] = f"refactor(catalog): remove question #{deleted_item.get('id')}"
        result["pr_summary"] = (
            f"### 🗑️ Inspection Question Removed\n\n"
            f"- **Question ID**: `#{deleted_item.get('id')}`\n"
            f"- **Language**: `{deleted_item.get('language')}`\n"
            f"- **Removed Question**: {deleted_item.get('question_text')}\n"
            f"- **Category**: {deleted_item.get('category')}\n\n"
            f"**Motivation**: {justification or '_Not provided_'}"
        )

    elif action == "translate":
        # Add translated version
        next_id = max([q.get("id", 0) for q in questions], default=0) + 1
        new_entry = {
            "id": next_id,
            "question_text": q_text,
            "themes": themes,
            "category": cat,
            "advice_notes": advice,
            "language": lang
        }
        questions.append(new_entry)
        save_questions(questions)

        result["success"] = True
        result["commit_title"] = f"feat(catalog): add translation ({lang}) for question"
        result["pr_title"] = f"feat(catalog): add translation [{lang.upper()}] for inspection question"
        result["pr_summary"] = (
            f"### 🌐 Inspection Question Translation Added\n\n"
            f"- **Target Language**: `{lang}`\n"
            f"- **Source Reference**: {target_text or '_Not specified_'}\n"
            f"- **Translated Question**: {q_text}\n"
            f"- **Category**: {cat}\n"
            f"- **Themes**: {', '.join(themes)}\n"
            f"- **Advice Notes**: {advice or '_None_'}\n\n"
            f"**Motivation**: {justification or '_Not provided_'}"
        )

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_catalog_question_issue.py <issue_body_or_path> [issue_number]")
        sys.exit(1)

    raw_input = sys.argv[1]
    issue_number = sys.argv[2] if len(sys.argv) >= 3 else "0"

    # Check if input is a file path
    if Path(raw_input).is_file():
        with open(raw_input, "r", encoding="utf-8") as f:
            issue_body = f.read()
    else:
        issue_body = raw_input

    res = process_catalog_issue(issue_body)
    print(json.dumps(res, ensure_ascii=False, indent=2))

    if not res["success"]:
        print(f"[Error] {res.get('error')}", file=sys.stderr)
        sys.exit(1)
