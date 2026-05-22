System Inputs
Access Request

Example: "I'm the on-call nurse; I need patient X's medical record."

Format: Natural language text

Context

Example: Time: 3:00 AM, Location: ER, Role: Nurse, History: 5 prior approved accesses

Format: JSON/Structured

Access Rules

Example: "Grant if (role = healthcare_professional AND time > 10PM AND time < 6AM)"

Format: Formal logic (XACML)

Feedback

Example: Audit logs: "Access denied at 3:05 AM for record Y (reason: role mismatch)"

Format: Structured (CSV/JSON)

System Outputs
Decision

Example: {"access": "granted", "confidence": 0.92, "reason": "emergency context validated"}

Format: JSON

Cache Update

Example: Store request embedding + decision + context

Format: Vector DB (FAISS)

Alert

Example: "Anomaly detected: High similarity to known privilege escalation attack (score: 0.87)"

Format: Notification