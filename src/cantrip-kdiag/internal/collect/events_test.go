package collect_test

import (
	"context"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/collect"
)

func makeEvent(name, namespace, evType, reason, message, involvedKind, involvedName string, count int32, lastSeen time.Time) *corev1.Event {
	return &corev1.Event{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Type:       evType,
		Reason:     reason,
		Message:    message,
		Count:      count,
		InvolvedObject: corev1.ObjectReference{
			Kind: involvedKind,
			Name: involvedName,
		},
		LastTimestamp: metav1.NewTime(lastSeen),
	}
}

func TestEvents_ReturnsAllEvents(t *testing.T) {
	now := time.Now()
	ev1 := makeEvent("ev1", "dev", "Warning", "BackOff", "crash", "Pod", "redis-0", 3, now)
	ev2 := makeEvent("ev2", "dev", "Normal", "Pulled", "pulled", "Pod", "redis-0", 1, now.Add(-10*time.Second))
	client := fake.NewSimpleClientset(ev1, ev2)

	events, err := collect.Events(context.Background(), client, "dev", 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 events, got %d", len(events))
	}
}

func TestEvents_LimitsToMaxEvents(t *testing.T) {
	now := time.Now()
	ev1 := makeEvent("ev1", "dev", "Warning", "BackOff", "crash", "Pod", "redis-0", 1, now)
	ev2 := makeEvent("ev2", "dev", "Warning", "OOM", "oom", "Pod", "redis-0", 1, now.Add(-5*time.Second))
	ev3 := makeEvent("ev3", "dev", "Warning", "FailedSchedule", "sched", "Pod", "redis-0", 1, now.Add(-10*time.Second))
	client := fake.NewSimpleClientset(ev1, ev2, ev3)

	events, err := collect.Events(context.Background(), client, "dev", 2)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 events (capped), got %d", len(events))
	}
}

func TestEvents_ReturnsEmptySliceWhenNone(t *testing.T) {
	client := fake.NewSimpleClientset()

	events, err := collect.Events(context.Background(), client, "dev", 10)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if events == nil {
		t.Error("expected non-nil empty slice, got nil")
	}
	if len(events) != 0 {
		t.Errorf("expected 0 events, got %d", len(events))
	}
}

func TestEvents_InvolvedObjectFormatted(t *testing.T) {
	ev := makeEvent("ev1", "dev", "Warning", "BackOff", "crash", "Pod", "redis-0", 1, time.Now())
	client := fake.NewSimpleClientset(ev)

	events, err := collect.Events(context.Background(), client, "dev", 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event")
	}
	if events[0].InvolvedObject != "Pod/redis-0" {
		t.Errorf("expected 'Pod/redis-0', got %q", events[0].InvolvedObject)
	}
}
