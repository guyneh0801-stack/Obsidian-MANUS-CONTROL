<%*
const relationOptions = [
  "person_works_for_organization",
  "person_owns_organization",
  "person_controls_organization",
  "organization_owns_organization",
  "organization_funds_organization",
  "person_affiliated_with_organization",
  "account_operated_by_person",
  "account_affiliated_with_organization",
  "account_posts_content",
  "source_mentions_entity",
  "source_evidences_relationship",
  "domain_operated_by_entity",
  "digital_asset_linked_to_account",
  "location_associated_with_entity",
  "same_as",
  "possible_same_as",
  "contradicts",
  "amplifies",
  "coordinates_with",
  "appears_with",
  "other"
];
const fromEntity = await tp.system.prompt("From entity — preferably [[link]]");
const relation = await tp.system.suggester(relationOptions, relationOptions);
const toEntity = await tp.system.prompt("To entity — preferably [[link]]");
const source = await tp.system.prompt("Primary supporting source — preferably [[link]]");
const relatedCase = await tp.system.prompt("Related case — preferably [[link]]");
const confidence = await tp.system.suggester(["low", "medium", "high", "unassessed"], ["low", "medium", "high", "unassessed"]);
const status = await tp.system.suggester(["hypothesis", "probable", "confirmed", "rejected"], ["hypothesis", "probable", "confirmed", "rejected"]);
%>
---
type: relationship-note
title: "<% tp.file.title %>"
status: "<% status %>"
created: <% tp.date.now("YYYY-MM-DD HH:mm") %>
relationship_type: "<% relation %>"
from_entity: "<% fromEntity %>"
to_entity: "<% toEntity %>"
direction: directed
strength: unassessed
confidence: "<% confidence %>"
related_case: "<% relatedCase %>"
linked_sources:
  - "<% source %>"
derived_insights: []
tags:
  - osint/relationship
  - osint/relationship/<% relation %>
---

# <% tp.file.title %>

## Relationship statement

<% fromEntity %> — **<% relation %>** — <% toEntity %>

## Evidence table

| Source | Evidence excerpt | Supports | Limitations |
| --- | --- | --- | --- |
| <% source %> |  |  |  |

## Analytical reasoning

הסבר מדוע המקור תומך בקשר. ציין האם מדובר בקשר ישיר, נסיבתי, טכני, חזותי, לשוני, כרונולוגי או רשתִי.

## Confidence assessment

| Dimension | Assessment | Reasoning |
| --- | --- | --- |
| Source reliability | unassessed |  |
| Directness of evidence | unassessed |  |
| Corroboration | unassessed |  |
| Alternative explanations | unassessed |  |
| Overall confidence | <% confidence %> |  |

## Red Team / איפכא מסתברא

מה יכול להפוך את הקשר הזה למקרי, מטעה, מיושן או לא רלוונטי? אילו ראיות היו מחלישות אותו באופן ממשי?
