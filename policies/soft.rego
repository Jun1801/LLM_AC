package access

default soft_allow := {"allow": true, "reason_code": "SOFT_POLICY_PASS", "matched_rule": "default_allow"}

soft_allow := {"allow": false, "reason_code": "INCIDENT_CRITICAL", "matched_rule": "incident_guard"} if {
  input.context.incident_state == "critical"
} else := {
  "allow": false,
  "reason_code": "INCIDENT_ELEVATED_RESTRICTED_FAST_PATH",
  "matched_rule": "incident_elevated_confidential_guard",
} if {
  input.context.incident_state == "elevated"
  input.resource.sensitivity == "confidential"
} else := {
  "allow": false,
  "reason_code": "OUT_OF_HOURS_FAST_PATH_REVIEW",
  "matched_rule": "time_window_guard",
} if {
  access_hour_utc := time.clock(time.parse_rfc3339_ns(input.timestamp_utc))[0]
  access_hour_utc >= 2
  access_hour_utc < 6
}
