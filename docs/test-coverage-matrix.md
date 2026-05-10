# Test Coverage Matrix — Database Queries

> **Created:** 2026-05-09 | **Author:** Lambert (QA)
> **Test file:** `tests/test_database_queries.py`

## Coverage Summary

| Category | Test Count |
|----------|-----------|
| Graph Queries | 35 |
| Full-Text Search | 14 |
| Vector Search | 11 |
| Trigram Search | 5 |
| Combined/Hybrid | 4 |
| Dashboard Queries | 8 |
| Filter Queries | 6 |
| Index Verification | 5 |
| **Total** | **88** |

---

## User Story → Test Case Mapping

| US | Title | Test Case(s) | Query Type | What Is Tested |
|----|-------|-------------|------------|----------------|
| US-001 | Candidate attributes from Workday | `test_employee_node_has_required_properties` | Graph | Employee node carries all ontology-defined properties |
| US-001 | | `test_employee_count_minimum` | Graph | ≥100K employees loaded |
| US-001 | | `test_employee_workday_id_unique` | Graph | No duplicate workday_ids |
| US-001 | | `test_employee_skill_level_valid` | Graph | skill_level enum values valid |
| US-001 | | `test_employee_employment_status_valid` | Graph | employment_status enum values valid |
| US-003 | Data source provenance | `test_data_source_values_valid` | Graph | data_source ∈ {Workday, Workday+CV, CV Only} |
| US-003 | | `test_data_source_not_null` | Graph | No null data_source values |
| US-006 | EQF/MECES mapping | `test_studied_at_eqf_level_in_range` | Graph | STUDIED_AT.eqf_level 5–8 |
| US-006 | | `test_studied_at_meces_level_in_range` | Graph | STUDIED_AT.meces_level 1–4 |
| US-008 | Auto-mapping studies | `test_eqf_mapping_status_valid` | Graph | eqf_mapping_status ∈ {Mapped, Pending mapping} |
| US-008 | | `test_employee_eqf_level_matches_studied_at` | Graph | Employee.eqf_level == STUDIED_AT.eqf_level |
| US-008 | | `test_filter_by_eqf_level` | Graph/Filter | EQF level as filter criterion |
| US-009 | Multi-criteria search | `test_search_by_skill_name` | Graph | Single skill search returns results |
| US-009 | | `test_search_by_multiple_skills` | Graph | AND of two skills |
| US-009 | | `test_search_by_skill_and_certification` | Graph | Skill + valid cert combined |
| US-009 | | `test_search_by_skill_location_language` | Graph | Skill + location + language |
| US-009 | | `test_has_skill_level_values_valid` | Graph | HAS_SKILL.level enum validation |
| US-009 | | `test_impressiveness_score_range` | Graph | Score 0–100 range |
| US-009 | | `test_search_results_sortable_by_impressiveness` | Graph | Sorting by impressiveness_score DESC |
| US-009 | | `test_cosine_similarity_resume_search` | Vector | Resume embedding similarity search |
| US-009 | | `test_cosine_similarity_skills_search` | Vector | Skills embedding similarity search |
| US-009 | | `test_vector_search_similarity_descending` | Vector | Results sorted by similarity |
| US-009 | | `test_vector_search_top_k_with_threshold` | Vector | Similarity threshold filtering |
| US-009 | | `test_trigram_name_search` | Trigram | Fuzzy name matching |
| US-009 | | `test_trigram_job_title_search` | Trigram | Fuzzy job title matching |
| US-009 | | `test_trigram_skills_text_search` | Trigram | Typo-tolerant skill search |
| US-009 | | `test_fts_plus_vector_combined_ranking` | Combined | Hybrid FTS + vector scoring |
| US-009 | | `test_embeddings_table_populated` | Vector | ≥100K embedding rows loaded |
| US-009 | | `test_resume_embedding_dimension` | Vector | resume_embedding is 1536-dim |
| US-009 | | `test_skills_embedding_dimension` | Vector | skills_embedding is 1536-dim |
| US-009 | | `test_resume_embedding_not_null` | Vector | <5% null resume embeddings |
| US-009 | | `test_skills_embedding_not_null` | Vector | <5% null skills embeddings |
| US-010 | Additional filters | `test_filter_by_location_city` | Graph | City filter (Madrid, Barcelona) |
| US-010 | | `test_filter_by_service_line` | Graph | Service line filter |
| US-010 | | `test_filter_by_job_level_range` | Graph | Job level range filter |
| US-010 | | `test_filter_by_delivery_model` | Graph | Delivery model enum + filter |
| US-010 | | `test_filter_by_bench_status` | Graph | Bench status filter |
| US-010 | | `test_filter_chain_location_then_language` | Filter | Progressive narrowing verified |
| US-010 | | `test_filter_preserves_original_count` | Filter | Filtered ≤ original count |
| US-010 | | `test_filter_by_offering` | Filter | Offering filter |
| US-010 | | `test_filter_by_language_proficiency` | Filter | Language proficiency level filter |
| US-010 | | `test_filter_by_cert_status` | Filter | Cert validity status filter |
| US-011 | Multiple positions | `test_multi_position_independent_queries` | Combined | Independent queries per position |
| US-012 | Triage attributes | `test_triage_attributes_available` | Graph | Key triage fields returned |
| US-014 | Skill gaps | `test_skill_gap_query_returns_uncovered_skills` | Graph | Uncovered skills identified |
| US-014 | | `test_skill_gap_partial_match_count` | Graph | Partial-match candidates counted |
| US-015 | Full-text search | `test_fts_table_populated` | FTS | ≥100K FTS rows |
| US-015 | | `test_fts_vector_not_null` | FTS | No null fts_vector values |
| US-015 | | `test_fts_plainto_tsquery_returns_results` | FTS | Plain-text keyword search |
| US-015 | | `test_fts_tsquery_boolean_and` | FTS | Boolean AND search |
| US-015 | | `test_fts_tsquery_boolean_or` | FTS | Boolean OR search |
| US-015 | | `test_fts_phrase_search` | FTS | Phrase proximity search |
| US-015 | | `test_fts_negation_search` | FTS | NOT operator in search |
| US-015 | | `test_fts_resume_summary_not_empty` | FTS | Resume text populated (≥90%) |
| US-015 | | `test_fts_skills_text_populated` | FTS | Skills text populated (≥95%) |
| US-015 | | `test_fts_rank_ordering` | FTS | ts_rank descending order |
| US-015 | | `test_fts_empty_query_returns_nothing` | FTS | Edge: empty query safe |
| US-015 | | `test_fts_special_characters_safe` | FTS | Edge: special chars safe |
| US-015 | | `test_graph_plus_fts_join` | Combined | Graph skill + FTS resume join |
| US-020 | Cert validity status | `test_cert_status_values_valid` | Graph | HOLDS_CERT.status enum valid |
| US-020 | | `test_cert_valid_has_issue_date` | Graph | Valid certs have issue_date |
| US-020 | | `test_cert_expired_not_flagged_valid` | Graph | Negative: expired != Valid |
| US-020 | | `test_fts_certs_text_populated` | FTS | certs_text populated (≥50%) |
| US-023 | Dashboard (certs/skills/langs) | `test_certification_count_by_type` | Dashboard | Cert count aggregation |
| US-023 | | `test_skills_distribution` | Dashboard | Skills distribution aggregation |
| US-023 | | `test_languages_distribution` | Dashboard | Languages distribution |
| US-023 | | `test_rfi_coverage_heat_map_query` | Dashboard | Heat map coverage levels |
| US-024 | My Team dashboard | `test_reports_to_returns_team_members` | Graph | REPORTS_TO traversal works |
| US-024 | | `test_reports_to_every_employee_has_manager` | Graph | No orphan employees |
| US-024 | | `test_my_team_scope_isolation` | Graph | Scope isolation per manager |
| US-024 | | `test_my_team_skills_aggregation` | Dashboard | Team skills aggregation |
| US-024 | | `test_my_team_languages_summary` | Dashboard | Team languages summary |
| US-025 | Full cert/competency profile | `test_employee_certifications_full_profile` | Graph | Full cert list for employee |
| US-026 | CV freshness indicators | `test_cv_freshness_days_not_negative` | Graph | No negative freshness |
| US-026 | | `test_cv_freshness_categories` | Graph | Freshness bucket distribution |
| US-026 | | `test_cv_freshness_aggregation` | Dashboard | Freshness indicator aggregation |
| US-026 | | `test_cert_status_aggregation` | Dashboard | Cert status indicator aggregation |
| US-028 | Skills baseline for My Team | `test_my_team_cert_aggregation` | Dashboard | Team cert baseline aggregation |
| US-032 | Tender doc / role extraction | `test_graph_plus_vector_join` | Combined | Cert graph + vector similarity |
| US-039 | Soft hold | `test_bench_employees_have_bench_start_date` | Graph | Bench metadata complete |
| US-041 | Infer skills from assignments | `test_worked_on_edges_have_role` | Graph | WORKED_ON has role for inference |
| US-041 | | `test_worked_for_client_edges_exist` | Graph | WORKED_FOR edges exist |
| US-046 | Multilanguage support | `test_fts_spanish_config` | FTS | Spanish language FTS config works |
| — | Structural integrity | `test_every_employee_has_location` | Graph | All employees have LOCATED_IN |
| — | | `test_every_employee_has_service_line` | Graph | All employees have BELONGS_TO_SL |
| — | | `test_every_employee_has_at_least_one_skill` | Graph | All employees have ≥1 skill |
| — | | `test_location_in_country_chain` | Graph | All locations linked to country |
| — | | `test_speaks_level_values_valid` | Graph | CEFR levels valid |
| — | | `test_skill_domain_names_valid` | Graph | 13 expected SkillDomains |
| — | | `test_embedding_workday_id_references_valid` | Vector | FK integrity: embeddings → FTS |
| — | | `test_embedding_ageid_unique` | Vector | Unique AGE IDs in embeddings |
| — | | `test_trigram_no_match_random_string` | Trigram | Negative: garbage returns 0 |
| — | | `test_trigram_threshold_configurable` | Trigram | pg_trgm threshold in valid range |
| — | Indexes | `test_gin_fts_index_exists` | Index | GIN index on fts_vector |
| — | | `test_trigram_indexes_exist` | Index | pg_trgm indexes on 3 columns |
| — | | `test_vector_index_exists` | Index | DiskANN/HNSW on resume_embedding |
| — | | `test_btree_workday_id_indexes` | Index | B-tree on workday_id columns |
| — | | `test_age_employee_workday_id_index` | Index | AGE Employee.workday_id index |

---

## Stories Not Covered (out of scope for DB query tests)

| US | Title | Reason |
|----|-------|--------|
| US-002 | CV artifact retrieval | Blob/file storage, not DB query |
| US-004 | Production quality data | Data pipeline integration test |
| US-005 | My Growth API ingestion | API integration test |
| US-007 | Admin EQF/MECES maintenance | CRUD/UI test |
| US-013 | Export to Excel/CSV/PDF/PPTX | Export/rendering test |
| US-016–019 | CV generation/anonymization | Document generation test |
| US-021–022 | Cert download/packaging | File handling test |
| US-027 | Access reports from dashboard | UI navigation test |
| US-029–031 | Reminder campaigns | Notification/workflow test |
| US-033–036 | Tender/RFI workflow | UI workflow test |
| US-037–038 | RBAC / DPIA | Auth/security test |
| US-040 | Soft-hold history | CRUD/audit test |
| US-042 | AI-assisted skill extraction | NLP pipeline test |
| US-043 | Feedback (thumbs up/down) | UI interaction test |
| US-044 | Help and FAQs | Content/UI test |
| US-045 | Query history | Session persistence test |
| US-047–052 | CPQ integration | External API integration test |
