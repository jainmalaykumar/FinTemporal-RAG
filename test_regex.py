import re
from collections import Counter

def extract_financial_year(text: str) -> int:
    years = []
    # Match FY24 -> 2024
    fy_matches = re.findall(r'\bFY(\d{2})\b', text, re.IGNORECASE)
    for m in fy_matches:
        years.append(2000 + int(m))
        
    # Match 2024-25 -> 2025
    fy_range_matches = re.findall(r'\b20\d{2}-(\d{2})\b', text)
    for m in fy_range_matches:
        years.append(2000 + int(m))
        
    # Match 2024-2025 -> 2025
    fy_range_full_matches = re.findall(r'\b20\d{2}-(20\d{2})\b', text)
    for m in fy_range_full_matches:
        years.append(int(m))

    # Match standard 4-digit years (e.g., 2024)
    year_matches = re.findall(r'\b(20\d{2})\b', text)
    for m in year_matches:
        years.append(int(m))
        
    if not years:
        return 2026
        
    counter = Counter(years)
    return counter.most_common(1)[0][0]

tests = [
    "Annual report for FY24 and FY24 is good. Also FY23.",
    "Report for 2024-25 is out. Also 2024-25. 2023.",
    "Year 2024 was great. 2024 rocks.",
    "Financial year 2023-2024",
    "No year here"
]

for t in tests:
    print(f"'{t}' -> {extract_financial_year(t)}")
