package access

default hard_allow := {"allow": false, "reason_code": "DEFAULT_DENY"}

hard_allow := {"allow": false, "reason_code": "MFA_REQUIRED", "matched_rule": "mfa_required"} if {
  input.context.mfa_state != "passed"
} else := {"allow": false, "reason_code": "SESSION_INVALID", "matched_rule": "session_required"} if {
  input.context.session_id == ""
} else := {"allow": false, "reason_code": "CLEARANCE_TOO_LOW", "matched_rule": "clearance_guard"} if {
  required_clearance := required_clearance_for_sensitivity(input.resource.sensitivity)
  input.user.clearance_level < required_clearance
} else := {"allow": false, "reason_code": "ROLE_RESOURCE_DENIED", "matched_rule": "role_resource_guard"} if {
  not allowed_role_resource
} else := {"allow": true, "reason_code": "HARD_POLICY_PASS", "matched_rule": "default_allow"} if {
  true
}

required_clearance_for_sensitivity(sensitivity) := 0 if {
  sensitivity == "public"
}

required_clearance_for_sensitivity(sensitivity) := 1 if {
  sensitivity == "internal"
}

required_clearance_for_sensitivity(sensitivity) := 2 if {
  sensitivity == "restricted"
}

required_clearance_for_sensitivity(sensitivity) := 3 if {
  sensitivity == "confidential"
}

allowed_role_resource if {
  input.user.role == "analyst"
  input.resource.resource_type in {"document", "report", "dashboard"}
}

allowed_role_resource if {
  input.user.role == "manager"
  input.resource.resource_type in {"document", "report", "dashboard", "ticket"}
}

allowed_role_resource if {
  input.user.role == "auditor"
  input.resource.resource_type in {"document", "report", "dataset", "dashboard"}
}

allowed_role_resource if {
  input.user.role == "engineer"
  input.resource.resource_type in {"document", "dashboard", "dataset"}
}

allowed_role_resource if {
  input.user.role == "security_analyst"
  input.resource.resource_type in {"document", "dataset", "dashboard", "ticket"}
}

allowed_role_resource if {
  input.user.role == "hr_partner"
  input.resource.resource_type in {"document", "report", "dataset"}
}

allowed_role_resource if {
  input.user.role == "legal_counsel"
  input.resource.resource_type in {"document", "dataset", "ticket"}
}
