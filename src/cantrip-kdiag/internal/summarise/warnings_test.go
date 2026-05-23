package summarise_test

import (
	"strings"
	"testing"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/summarise"
)

func TestWarnings_CrashLoopBackOff(t *testing.T) {
	pods := []output.PodInfo{
		{
			Name: "redis-k8s-0",
			Containers: []output.ContainerInfo{
				{Name: "redis", WaitingReason: "CrashLoopBackOff"},
			},
		},
	}
	warnings := summarise.Warnings(pods, nil, nil)

	if len(warnings) != 1 {
		t.Fatalf("expected 1 warning, got %d: %v", len(warnings), warnings)
	}
	if !strings.Contains(warnings[0], "CrashLoopBackOff") {
		t.Errorf("expected CrashLoopBackOff in warning, got %q", warnings[0])
	}
	if !strings.Contains(warnings[0], "redis-k8s-0") {
		t.Errorf("expected pod name in warning, got %q", warnings[0])
	}
}

func TestWarnings_OOMKilled(t *testing.T) {
	pods := []output.PodInfo{
		{
			Name: "redis-k8s-0",
			Containers: []output.ContainerInfo{
				{Name: "redis", TerminatedReason: "OOMKilled"},
			},
		},
	}
	warnings := summarise.Warnings(pods, nil, nil)

	if len(warnings) != 1 {
		t.Fatalf("expected 1 warning, got %d", len(warnings))
	}
	if !strings.Contains(warnings[0], "OOMKilled") {
		t.Errorf("expected OOMKilled in warning, got %q", warnings[0])
	}
}

func TestWarnings_CompletedContainerNoWarning(t *testing.T) {
	// "Completed" is a normal terminal state, not a warning.
	pods := []output.PodInfo{
		{
			Name: "init-pod",
			Containers: []output.ContainerInfo{
				{Name: "init", TerminatedReason: "Completed"},
			},
		},
	}
	warnings := summarise.Warnings(pods, nil, nil)
	if len(warnings) != 0 {
		t.Errorf("expected no warnings for Completed containers, got %v", warnings)
	}
}

func TestWarnings_PVCPending(t *testing.T) {
	pvcs := []output.PVCInfo{
		{Name: "data-redis-k8s-0", Phase: "Pending"},
	}
	warnings := summarise.Warnings(nil, pvcs, nil)

	if len(warnings) != 1 {
		t.Fatalf("expected 1 warning, got %d", len(warnings))
	}
	if !strings.Contains(warnings[0], "pvc data-redis-k8s-0") {
		t.Errorf("expected PVC name in warning, got %q", warnings[0])
	}
	if !strings.Contains(warnings[0], "Pending") {
		t.Errorf("expected Pending in warning, got %q", warnings[0])
	}
}

func TestWarnings_BoundPVCNoWarning(t *testing.T) {
	pvcs := []output.PVCInfo{{Name: "data", Phase: "Bound"}}
	warnings := summarise.Warnings(nil, pvcs, nil)
	if len(warnings) != 0 {
		t.Errorf("expected no warning for Bound PVC, got %v", warnings)
	}
}

func TestWarnings_WarningEvent(t *testing.T) {
	events := []output.EventInfo{
		{
			Type:          "Warning",
			Reason:        "FailedScheduling",
			Message:       "0/1 nodes available",
			InvolvedObject: "Pod/redis-k8s-0",
		},
	}
	warnings := summarise.Warnings(nil, nil, events)

	if len(warnings) != 1 {
		t.Fatalf("expected 1 warning, got %d", len(warnings))
	}
	if !strings.Contains(warnings[0], "FailedScheduling") {
		t.Errorf("expected FailedScheduling in warning, got %q", warnings[0])
	}
}

func TestWarnings_NormalEventNoWarning(t *testing.T) {
	events := []output.EventInfo{{Type: "Normal", Reason: "Pulled"}}
	warnings := summarise.Warnings(nil, nil, events)
	if len(warnings) != 0 {
		t.Errorf("expected no warning for Normal event, got %v", warnings)
	}
}

func TestWarnings_EmptyInputReturnsEmptySlice(t *testing.T) {
	warnings := summarise.Warnings(nil, nil, nil)
	if warnings == nil {
		t.Error("expected non-nil empty slice, got nil")
	}
	if len(warnings) != 0 {
		t.Errorf("expected 0 warnings, got %d", len(warnings))
	}
}

func TestStats_Counts(t *testing.T) {
	exitCode := int32(1)
	pods := []output.PodInfo{
		{Name: "a", Ready: true, RestartCount: 0},
		{Name: "b", Ready: false, RestartCount: 3},
		{Name: "c", Ready: false, RestartCount: 0,
			Containers: []output.ContainerInfo{{LastExitCode: &exitCode}}},
	}
	pvcs := []output.PVCInfo{
		{Phase: "Pending"},
		{Phase: "Bound"},
	}
	events := []output.EventInfo{
		{Type: "Warning"},
		{Type: "Warning"},
		{Type: "Normal"},
	}

	stats := summarise.Stats(pods, pvcs, events)

	if stats.PodCount != 3 {
		t.Errorf("expected PodCount=3, got %d", stats.PodCount)
	}
	if stats.ReadyPods != 1 {
		t.Errorf("expected ReadyPods=1, got %d", stats.ReadyPods)
	}
	if stats.RestartingPods != 1 {
		t.Errorf("expected RestartingPods=1 (only pod b has restarts), got %d", stats.RestartingPods)
	}
	if stats.PVCPendingCount != 1 {
		t.Errorf("expected PVCPendingCount=1, got %d", stats.PVCPendingCount)
	}
	if stats.WarningEventCount != 2 {
		t.Errorf("expected WarningEventCount=2, got %d", stats.WarningEventCount)
	}
}
