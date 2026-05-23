package output_test

import (
	"bytes"
	"encoding/json"
	"testing"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
)

func TestWriteJSON_ProducesValidJSON(t *testing.T) {
	report := output.Report{
		SchemaVersion: output.SchemaVersion,
		Pods:          []output.PodInfo{},
		PVCs:          []output.PVCInfo{},
		Events:        []output.EventInfo{},
		Warnings:      []string{},
	}
	var buf bytes.Buffer
	if err := output.WriteJSON(&buf, report); err != nil {
		t.Fatalf("WriteJSON failed: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(buf.Bytes(), &out); err != nil {
		t.Fatalf("output is not valid JSON: %v\n%s", err, buf.String())
	}
}

func TestWriteJSON_SchemaVersionPresent(t *testing.T) {
	report := output.Report{SchemaVersion: output.SchemaVersion}
	var buf bytes.Buffer
	_ = output.WriteJSON(&buf, report)

	var out map[string]any
	_ = json.Unmarshal(buf.Bytes(), &out)
	v, ok := out["schema_version"]
	if !ok {
		t.Fatal("schema_version field missing from output")
	}
	if int(v.(float64)) != output.SchemaVersion {
		t.Errorf("expected schema_version=%d, got %v", output.SchemaVersion, v)
	}
}

func TestWriteError_ProducesErrorShape(t *testing.T) {
	var buf bytes.Buffer
	output.WriteError(&buf, "context_not_found", "Context 'dev' not found")

	var out map[string]any
	if err := json.Unmarshal(buf.Bytes(), &out); err != nil {
		t.Fatalf("error response is not valid JSON: %v", err)
	}
	if _, ok := out["error"]; !ok {
		t.Fatal("error field missing from error response")
	}
	errObj := out["error"].(map[string]any)
	if errObj["code"] != "context_not_found" {
		t.Errorf("expected code=context_not_found, got %v", errObj["code"])
	}
}

func TestReport_ArrayFieldsNeverNull(t *testing.T) {
	// Pods/PVCs/Events/Warnings must be [] not null in the JSON output.
	report := output.Report{
		SchemaVersion: output.SchemaVersion,
		Pods:          []output.PodInfo{},
		PVCs:          []output.PVCInfo{},
		Events:        []output.EventInfo{},
		Warnings:      []string{},
	}
	var buf bytes.Buffer
	_ = output.WriteJSON(&buf, report)

	raw := buf.String()
	// The indented encoder inserts spaces after ":" so check for "key": []
	for _, field := range []string{`"pods": []`, `"pvcs": []`, `"events": []`, `"warnings": []`} {
		if !bytes.Contains(buf.Bytes(), []byte(field)) {
			t.Errorf("expected %q in JSON output, got:\n%s", field, raw)
		}
	}
}

func TestPreflightReport_Shape(t *testing.T) {
	rep := output.PreflightReport{
		SchemaVersion:    output.SchemaVersion,
		KubeconfigPath:   "/home/user/.kube/config",
		Context:          "dev",
		APIReachable:     true,
		MetricsAvailable: false,
	}
	var buf bytes.Buffer
	if err := output.WriteJSON(&buf, rep); err != nil {
		t.Fatalf("WriteJSON failed: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(buf.Bytes(), &out); err != nil {
		t.Fatalf("preflight output is not valid JSON: %v", err)
	}
	if out["api_reachable"] != true {
		t.Errorf("expected api_reachable=true, got %v", out["api_reachable"])
	}
	if out["metrics_available"] != false {
		t.Errorf("expected metrics_available=false, got %v", out["metrics_available"])
	}
}
