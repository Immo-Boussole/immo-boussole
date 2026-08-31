"""
vCard 3.0 parser and generator for Immo-Boussole agents and agencies.
Handles single and multi-vCard streams, UTF-8 line folding, character escaping,
and bidirectional conversion between database models and VCF text format.
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from app.models import Agent, Agency


def _escape_vcard(text: Optional[str]) -> str:
    """Escapes special characters in vCard text values per RFC 2426."""
    if not text:
        return ""
    res = str(text)
    res = res.replace("\\", "\\\\")
    res = res.replace(";", "\\;")
    res = res.replace(",", "\\,")
    res = res.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return res


def _unescape_vcard(text: Optional[str]) -> str:
    """Unescapes vCard text values."""
    if not text:
        return ""
    res = str(text)
    res = res.replace("\\n", "\n").replace("\\N", "\n")
    res = res.replace("\\,", ",")
    res = res.replace("\\;", ";")
    res = res.replace("\\\\", "\\")
    return res.strip()


def _format_vcard_line(key: str, val: str) -> str:
    """Formats a single vCard property line with CRLF termination."""
    if not val:
        return ""
    line = f"{key}:{val}"
    # Standard vCard line folding at 75 octets
    if len(line.encode("utf-8")) <= 75:
        return f"{line}\r\n"
    
    # Fold line
    buf = []
    current = ""
    for char in line:
        if len((current + char).encode("utf-8")) > 74:
            buf.append(current)
            current = " " + char
        else:
            current += char
    if current:
        buf.append(current)
    return "\r\n".join(buf) + "\r\n"


def generate_agent_vcard(agent: Agent) -> str:
    """Generates a vCard 3.0 string representation of an Agent."""
    first = _escape_vcard(agent.first_name)
    last = _escape_vcard(agent.last_name)
    fn = _escape_vcard(f"{agent.first_name} {agent.last_name}".strip())
    
    lines = [
        "BEGIN:VCARD\r\n",
        "VERSION:3.0\r\n",
        _format_vcard_line("N", f"{last};{first};;;"),
        _format_vcard_line("FN", fn),
    ]
    
    if agent.title:
        lines.append(_format_vcard_line("TITLE", _escape_vcard(agent.title)))
        
    if agent.phone_mobile:
        lines.append(_format_vcard_line("TEL;TYPE=CELL", _escape_vcard(agent.phone_mobile)))
        
    if agent.phone_landline:
        lines.append(_format_vcard_line("TEL;TYPE=WORK,VOICE", _escape_vcard(agent.phone_landline)))
        
    if agent.email:
        lines.append(_format_vcard_line("EMAIL;TYPE=INTERNET", _escape_vcard(agent.email)))
        
    agency_name = None
    if agent.agency:
        agency_name = agent.agency.commercial_name or agent.agency.legal_name
    if agency_name:
        lines.append(_format_vcard_line("ORG", _escape_vcard(agency_name)))
        
    notes = []
    if agent.internal_notes:
        notes.append(agent.internal_notes)
    if agent.commission_rate is not None:
        notes.append(f"Commission: {agent.commission_rate}%")
    if agent.communication_prefs:
        notes.append(f"Préférences: {agent.communication_prefs}")
        
    if notes:
        lines.append(_format_vcard_line("NOTE", _escape_vcard("\n".join(notes))))
        
    lines.append("END:VCARD\r\n")
    return "".join([l for l in lines if l])


def generate_agency_vcard(agency: Agency) -> str:
    """Generates a vCard 3.0 string representation of an Agency."""
    name = agency.commercial_name or agency.legal_name
    esc_name = _escape_vcard(name)
    
    lines = [
        "BEGIN:VCARD\r\n",
        "VERSION:3.0\r\n",
        _format_vcard_line("N", f"{esc_name};;;;"),
        _format_vcard_line("FN", esc_name),
        _format_vcard_line("ORG", esc_name),
    ]
    
    if agency.phone:
        lines.append(_format_vcard_line("TEL;TYPE=WORK,VOICE", _escape_vcard(agency.phone)))
        
    if agency.email:
        lines.append(_format_vcard_line("EMAIL;TYPE=INTERNET", _escape_vcard(agency.email)))
        
    if agency.website:
        lines.append(_format_vcard_line("URL", _escape_vcard(agency.website)))
        
    street = _escape_vcard(agency.address or "")
    city = _escape_vcard(agency.city or "")
    zip_code = _escape_vcard(agency.postal_code or "")
    if street or city or zip_code:
        # Format ADR: PO Box; Extended Address; Street Address; Locality; Region; Postal Code; Country Name
        adr_val = f";;{street};{city};;{zip_code};France"
        lines.append(_format_vcard_line("ADR;TYPE=WORK", adr_val))
        
    notes = []
    if agency.legal_name and agency.legal_name != name:
        notes.append(f"Raison sociale: {agency.legal_name}")
    if agency.siret:
        notes.append(f"SIRET: {agency.siret}")
    if agency.carte_t_number:
        notes.append(f"Carte T: {agency.carte_t_number}")
    if agency.reputation_notes:
        notes.append(agency.reputation_notes)
        
    if notes:
        lines.append(_format_vcard_line("NOTE", _escape_vcard("\n".join(notes))))
        
    lines.append("END:VCARD\r\n")
    return "".join([l for l in lines if l])


def generate_multi_vcard(agents: List[Agent], agencies: List[Agency]) -> str:
    """Combines multiple agents and agencies into a single multi-vCard stream."""
    blocks = []
    for agency in agencies:
        blocks.append(generate_agency_vcard(agency))
    for agent in agents:
        blocks.append(generate_agent_vcard(agent))
    return "\r\n".join(blocks)


def parse_vcard_stream(vcard_content: str) -> List[Dict[str, Any]]:
    """
    Parses a string containing one or multiple vCard 3.0 / 2.1 / 4.0 blocks.
    Returns a list of parsed contact/agency dictionary objects.
    """
    if not vcard_content:
        return []
        
    # Unfold continuation lines (lines starting with space or tab)
    raw_lines = vcard_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded_lines: List[str] = []
    for line in raw_lines:
        if (line.startswith(" ") or line.startswith("\t")) and unfolded_lines:
            unfolded_lines[-1] += line[1:]
        else:
            unfolded_lines.append(line)
            
    # Group into VCARD blocks
    cards: List[List[str]] = []
    current_card: Optional[List[str]] = None
    
    for line in unfolded_lines:
        sline = line.strip()
        if sline.upper() == "BEGIN:VCARD":
            current_card = []
        elif sline.upper() == "END:VCARD":
            if current_card is not None:
                cards.append(current_card)
                current_card = None
        elif current_card is not None and sline:
            current_card.append(sline)
            
    parsed_items: List[Dict[str, Any]] = []
    
    for card_lines in cards:
        props: Dict[str, List[Tuple[str, str]]] = {}
        
        for line in card_lines:
            if ":" not in line:
                continue
            head, val = line.split(":", 1)
            parts = head.split(";")
            key = parts[0].upper()
            params = parts[1:] if len(parts) > 1 else []
            param_str = ";".join(params).upper()
            props.setdefault(key, []).append((param_str, val.strip()))
            
        if not props:
            continue
            
        # Extract fields
        n_vals = props.get("N", [])
        fn_vals = props.get("FN", [])
        org_vals = props.get("ORG", [])
        title_vals = props.get("TITLE", [])
        tel_vals = props.get("TEL", [])
        email_vals = props.get("EMAIL", [])
        url_vals = props.get("URL", [])
        adr_vals = props.get("ADR", [])
        note_vals = props.get("NOTE", [])
        kind_vals = props.get("X-ABSHOWAS", []) or props.get("KIND", [])
        
        first_name = ""
        last_name = ""
        if n_vals:
            raw_n = _unescape_vcard(n_vals[0][1])
            n_parts = raw_n.split(";")
            last_name = n_parts[0].strip() if len(n_parts) > 0 else ""
            first_name = n_parts[1].strip() if len(n_parts) > 1 else ""
            
        fn = _unescape_vcard(fn_vals[0][1]) if fn_vals else ""
        org_name = _unescape_vcard(org_vals[0][1]).replace(";", " ").strip() if org_vals else ""
        title = _unescape_vcard(title_vals[0][1]) if title_vals else ""
        email = _unescape_vcard(email_vals[0][1]) if email_vals else ""
        website = _unescape_vcard(url_vals[0][1]) if url_vals else ""
        notes = "\n".join([_unescape_vcard(nv[1]) for nv in note_vals]) if note_vals else ""
        
        phone_mobile = ""
        phone_landline = ""
        phone_general = ""
        
        for params, tel_num in tel_vals:
            clean_num = _unescape_vcard(tel_num)
            if "CELL" in params or "MOBILE" in params:
                if not phone_mobile:
                    phone_mobile = clean_num
            elif "WORK" in params or "VOICE" in params or "HOME" in params:
                if not phone_landline:
                    phone_landline = clean_num
            else:
                if not phone_general:
                    phone_general = clean_num
                    
        if not phone_mobile and phone_general:
            phone_mobile = phone_general
            
        street, city, zip_code = "", "", ""
        if adr_vals:
            adr_raw = _unescape_vcard(adr_vals[0][1])
            adr_parts = adr_raw.split(";")
            street = adr_parts[2].strip() if len(adr_parts) > 2 else ""
            city = adr_parts[3].strip() if len(adr_parts) > 3 else ""
            zip_code = adr_parts[5].strip() if len(adr_parts) > 5 else ""

        is_org_kind = any("COMPANY" in kv[1].upper() or "ORG" in kv[1].upper() for kv[1] in kind_vals)
        
        # Determine if card represents an Agency
        # An Agency typically has ORG equal/similar to FN or N, or has ORG without TITLE or CELL phone, or has KIND:org
        is_agency = False
        if is_org_kind:
            is_agency = True
        elif org_name:
            org_clean = org_name.lower()
            fn_clean = fn.lower()
            last_clean = last_name.lower()
            if org_clean == fn_clean or org_clean == last_clean or not first_name:
                if not title and not phone_mobile:
                    is_agency = True
        elif not first_name and not last_name and fn:
            if not title and not phone_mobile:
                is_agency = True

        if not is_agency and not first_name and not last_name and fn:
            fn_parts = fn.split(None, 1)
            first_name = fn_parts[0] if len(fn_parts) > 0 else ""
            last_name = fn_parts[1] if len(fn_parts) > 1 else ""

        if is_agency:
            agency_name = org_name or fn or f"{last_name} {first_name}".strip() or "Agence Importée"
            parsed_items.append({
                "type": "agency",
                "name": agency_name,
                "legal_name": agency_name,
                "commercial_name": agency_name,
                "phone": phone_landline or phone_mobile or phone_general,
                "email": email,
                "website": website,
                "address": street,
                "city": city,
                "postal_code": zip_code,
                "reputation_notes": notes
            })
        else:
            parsed_items.append({
                "type": "agent",
                "first_name": first_name or "Inconnu",
                "last_name": last_name or (fn if fn != first_name else "Contact"),
                "name": f"{first_name} {last_name}".strip() or fn or "Contact Inconnu",
                "title": title or "Agent",
                "phone_mobile": phone_mobile,
                "phone_landline": phone_landline,
                "email": email,
                "agency_name": org_name,
                "internal_notes": notes
            })
            
    return parsed_items
