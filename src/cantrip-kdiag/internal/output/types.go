// Package output defines the JSON/text output contract for cantrip-kdiag.
package output

// SchemaVersion is the current JSON output schema version.
// Increment when the shape changes in a backwards-incompatible way.
const SchemaVersion = 1

// Report is the top-level JSON output for summary and pod commands.
type Report struct {
	SchemaVersion    int          `json:"schema_version"`
	GeneratedAt      string       `json:"generated_at"`
	Context          ContextInfo  `json:"context"`
	Query            QueryInfo    `json:"query"`
	MetricsAvailable bool         `json:"metrics_available"`
	Pods             []PodInfo    `json:"pods"`
	PVCs             []PVCInfo    `json:"pvcs"`
	Events           []EventInfo  `json:"events"`
	Warnings         []string     `json:"warnings"`
	Summary          SummaryStats `json:"summary"`
}

// PreflightReport is the JSON output for the preflight command.
type PreflightReport struct {
	SchemaVersion    int    `json:"schema_version"`
	KubeconfigPath   string `json:"kubeconfig"`
	Context          string `json:"context"`
	APIReachable     bool   `json:"api_reachable"`
	MetricsAvailable bool   `json:"metrics_available"`
}

// ErrorResponse is returned on failures that can be reported to the caller.
type ErrorResponse struct {
	SchemaVersion int         `json:"schema_version"`
	Error         ErrorDetail `json:"error"`
}

// ErrorDetail holds the machine-friendly error code and human message.
type ErrorDetail struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// ContextInfo describes the kubeconfig/context/namespace used for the query.
type ContextInfo struct {
	KubeconfigPath string `json:"kubeconfig"`
	Context        string `json:"context"`
	Namespace      string `json:"namespace"`
}

// QueryInfo describes the targeting filter applied to the query.
type QueryInfo struct {
	App  *string `json:"app"`
	Unit *string `json:"unit"`
	Pod  *string `json:"pod"`
}

// PodInfo is the per-pod diagnostic entry included in Report.Pods.
type PodInfo struct {
	Name         string            `json:"name"`
	Phase        string            `json:"phase"`
	Ready        bool              `json:"ready"`
	RestartCount int32             `json:"restart_count"`
	Node         string            `json:"node"`
	OwnerKind    string            `json:"owner_kind,omitempty"`
	OwnerName    string            `json:"owner_name,omitempty"`
	Labels       map[string]string `json:"labels"`
	Containers   []ContainerInfo   `json:"containers"`
	// CPUMillicores is populated when the metrics API is available.
	CPUMillicores *int64 `json:"cpu_millicores,omitempty"`
	// MemoryMiB is populated when the metrics API is available.
	MemoryMiB *int64 `json:"memory_mib,omitempty"`
}

// ContainerInfo is the per-container diagnostic entry inside PodInfo.
type ContainerInfo struct {
	Name             string   `json:"name"`
	Image            string   `json:"image"`
	Ready            bool     `json:"ready"`
	RestartCount     int32    `json:"restart_count"`
	State            string   `json:"state"` // "running", "waiting", "terminated", "unknown"
	WaitingReason    string   `json:"waiting_reason,omitempty"`
	TerminatedReason string   `json:"terminated_reason,omitempty"`
	LastExitCode     *int32   `json:"last_exit_code,omitempty"`
	PreviousLogTail  []string `json:"previous_log_tail,omitempty"`
}

// PVCInfo is the per-PVC diagnostic entry included in Report.PVCs.
type PVCInfo struct {
	Name         string `json:"name"`
	Phase        string `json:"phase"`
	StorageClass string `json:"storage_class,omitempty"`
	Capacity     string `json:"capacity,omitempty"`
	AccessModes  string `json:"access_modes,omitempty"`
}

// EventInfo is the per-event entry included in Report.Events.
type EventInfo struct {
	Name          string `json:"name"`
	Reason        string `json:"reason"`
	Message       string `json:"message"`
	Count         int32  `json:"count"`
	Type          string `json:"type"` // "Normal" or "Warning"
	InvolvedObject string `json:"involved_object"`
	LastSeen      string `json:"last_seen"`
}

// SummaryStats is the aggregated counts included in Report.Summary.
type SummaryStats struct {
	PodCount          int `json:"pod_count"`
	ReadyPods         int `json:"ready_pods"`
	RestartingPods    int `json:"restarting_pods"`
	WarningEventCount int `json:"warning_event_count"`
	PVCPendingCount   int `json:"pvc_pending_count"`
}
