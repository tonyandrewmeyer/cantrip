package collect_test

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/collect"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
)

func makePod(name, namespace, phase string, ready bool) *corev1.Pod {
	readyStatus := corev1.ConditionFalse
	if ready {
		readyStatus = corev1.ConditionTrue
	}
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "app", Image: "example/app:latest"},
			},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodPhase(phase),
			Conditions: []corev1.PodCondition{
				{Type: corev1.PodReady, Status: readyStatus},
			},
			ContainerStatuses: []corev1.ContainerStatus{
				{
					Name:  "app",
					Ready: ready,
					State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}},
				},
			},
		},
	}
}

func TestPods_ReturnsAllPodsWithoutFilter(t *testing.T) {
	pod1 := makePod("redis-k8s-0", "dev", "Running", true)
	pod2 := makePod("redis-k8s-1", "dev", "Running", false)
	client := fake.NewSimpleClientset(pod1, pod2)

	pods, err := collect.Pods(context.Background(), client, "dev", kube.TargetFilter{}, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pods) != 2 {
		t.Errorf("expected 2 pods, got %d", len(pods))
	}
}

func TestPods_FiltersToMatchingPod(t *testing.T) {
	pod1 := makePod("redis-k8s-0", "dev", "Running", true)
	pod2 := makePod("other-app-0", "dev", "Running", true)
	client := fake.NewSimpleClientset(pod1, pod2)

	filter := kube.TargetFilter{Pod: "redis-k8s-0"}
	pods, err := collect.Pods(context.Background(), client, "dev", filter, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pods) != 1 {
		t.Fatalf("expected 1 pod, got %d", len(pods))
	}
	if pods[0].Name != "redis-k8s-0" {
		t.Errorf("expected redis-k8s-0, got %s", pods[0].Name)
	}
}

func TestPods_ReturnsEmptySliceWhenNoMatch(t *testing.T) {
	pod := makePod("other-0", "dev", "Running", true)
	client := fake.NewSimpleClientset(pod)

	filter := kube.TargetFilter{Pod: "redis-k8s-0"}
	pods, err := collect.Pods(context.Background(), client, "dev", filter, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if pods == nil {
		t.Error("expected non-nil empty slice, got nil")
	}
	if len(pods) != 0 {
		t.Errorf("expected 0 pods, got %d", len(pods))
	}
}

func TestPods_CrashLoopPodHasCorrectState(t *testing.T) {
	restartCount := int32(5)
	exitCode := int32(1)
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "redis-k8s-0", Namespace: "dev"},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{{Name: "redis", Image: "redis:7"}},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
			ContainerStatuses: []corev1.ContainerStatus{
				{
					Name:         "redis",
					Ready:        false,
					RestartCount: restartCount,
					State: corev1.ContainerState{
						Waiting: &corev1.ContainerStateWaiting{
							Reason: "CrashLoopBackOff",
						},
					},
					LastTerminationState: corev1.ContainerState{
						Terminated: &corev1.ContainerStateTerminated{
							ExitCode: exitCode,
						},
					},
				},
			},
		},
	}
	client := fake.NewSimpleClientset(pod)

	pods, err := collect.Pods(context.Background(), client, "dev", kube.TargetFilter{}, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pods) != 1 {
		t.Fatalf("expected 1 pod")
	}
	p := pods[0]
	if p.Ready {
		t.Error("pod should not be ready")
	}
	if p.RestartCount != restartCount {
		t.Errorf("expected restart count %d, got %d", restartCount, p.RestartCount)
	}
	if len(p.Containers) != 1 {
		t.Fatalf("expected 1 container")
	}
	c := p.Containers[0]
	if c.WaitingReason != "CrashLoopBackOff" {
		t.Errorf("expected CrashLoopBackOff, got %q", c.WaitingReason)
	}
	if c.LastExitCode == nil || *c.LastExitCode != exitCode {
		t.Errorf("expected last exit code %d", exitCode)
	}
}

func TestPods_ReadyPodIsMarkedReady(t *testing.T) {
	pod := makePod("ready-pod", "dev", "Running", true)
	client := fake.NewSimpleClientset(pod)

	pods, err := collect.Pods(context.Background(), client, "dev", kube.TargetFilter{}, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pods) != 1 {
		t.Fatalf("expected 1 pod")
	}
	if !pods[0].Ready {
		t.Error("pod with all containers ready should be marked ready")
	}
}

func TestPods_OwnerReferenceExtracted(t *testing.T) {
	isController := true
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "redis-k8s-0",
			Namespace: "dev",
			OwnerReferences: []metav1.OwnerReference{
				{Kind: "StatefulSet", Name: "redis-k8s", Controller: &isController},
			},
		},
		Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "c"}}},
	}
	client := fake.NewSimpleClientset(pod)

	pods, err := collect.Pods(context.Background(), client, "dev", kube.TargetFilter{}, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if pods[0].OwnerKind != "StatefulSet" {
		t.Errorf("expected OwnerKind=StatefulSet, got %q", pods[0].OwnerKind)
	}
	if pods[0].OwnerName != "redis-k8s" {
		t.Errorf("expected OwnerName=redis-k8s, got %q", pods[0].OwnerName)
	}
}

func TestSinglePod_ReturnsNamedPod(t *testing.T) {
	pod := makePod("redis-k8s-0", "dev", "Running", true)
	client := fake.NewSimpleClientset(pod)

	info, err := collect.SinglePod(context.Background(), client, "dev", "redis-k8s-0", 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Name != "redis-k8s-0" {
		t.Errorf("expected redis-k8s-0, got %s", info.Name)
	}
}
