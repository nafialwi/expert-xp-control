# XP+ Interface Contract Sweep — HC5

Authority: locked `XP_PLUS_v1_IMPLEMENTATION_PLAN.md` Produces/Interfaces entries for engine_lifecycle, schema, project_doctor, bundle, and compatibility.

The regression named below is executed separately by the gate runner. This table verifies that each locked public interface exists in the actual source and maps it to a non-mocked behavioral regression.

| Module | Locked interface | Public API | Non-mocked regression | Result |
|---|---|---|---|---|
| `xp.engine_lifecycle` | `EngineCandidate` | constructor | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.engine_lifecycle` | `EngineLifecycle.install_candidate` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.engine_lifecycle` | `EngineLifecycle.activate_candidate` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.engine_lifecycle` | `EngineLifecycle.rollback_to_previous` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.engine_lifecycle` | `EngineLifecycle.health_check` | callable + HC1 behavioral coverage | `XP10HealthAuthorityTests.test_default_health_authority_returns_structured_records_and_preserves_project_source` | PASS |
| `xp.schema` | `schema_for` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.schema` | `validate_spec_dict` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.project_doctor` | `ProjectDoctor.inspect` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.project_doctor` | `ProjectAudit.status/findings` | public dataclass fields | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.bundle` | `BundleBuilder.compact` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.bundle` | `BundleBuilder.deep` | callable | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |
| `xp.compatibility` | `CompatibilityAudit.run` | callable + read-only | `XP10InterfaceContractTests.test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks` | PASS |

## Standing lifecycle-default rule (HC8)

Every injectable dependency or callback on a lifecycle-critical production path must have a real engine-owned, regression-tested production default. Injection exists for tests; production defaults are the authority.

Incidents that established this permanent rule: XP+-08 V3 candidate-match masking and XP+-10 missing lifecycle health authority.
