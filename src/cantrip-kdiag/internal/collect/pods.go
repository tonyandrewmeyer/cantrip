// Package collect fetches read-only diagnostic data from the Kubernetes API.
package collect

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"strings"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
)

// PreviousLogLines is the default tail length for previous container logs.
const PreviousLogLines = 50

// Pods collects pod diagnostics from the given namespace.
// It applies the target filter and, for crashed containers, fetches previous
// log tails (bounded by maxPreviousLines).
func Pods(
	ctx context.Context,
	client kubernetes.Interface,
	namespace string,
	filter kube.TargetFilter,
	maxPreviousLines int64,
) ([]output.PodInfo, error) {
	list, err := client.CoreV1().Pods(namespace).List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("listing pods: %w", err)
	}

	var pods []output.PodInfo
	for i := range list.Items {
		pod := &list.Items[i]
		if !filter.MatchesPod(pod.Name, pod.Labels) {
			continue
		}
		info, err := podInfo(ctx, client, namespace, pod, maxPreviousLines)
		if err != nil {
			return nil, err
		}
		pods = append(pods, info)
	}
	if pods == nil {
		pods = []output.PodInfo{}
	}
	return pods, nil
}

// SinglePod fetches diagnostics for a specific pod by name.
func SinglePod(
	ctx context.Context,
	client kubernetes.Interface,
	namespace, podName string,
	maxPreviousLines int64,
) (output.PodInfo, error) {
	pod, err := client.CoreV1().Pods(namespace).Get(ctx, podName, metav1.GetOptions{})
	if err != nil {
		return output.PodInfo{}, fmt.Errorf("getting pod %s: %w", podName, err)
	}
	return podInfo(ctx, client, namespace, pod, maxPreviousLines)
}

func podInfo(
	ctx context.Context,
	client kubernetes.Interface,
	namespace string,
	pod *corev1.Pod,
	maxPreviousLines int64,
) (output.PodInfo, error) {
	labels := pod.Labels
	if labels == nil {
		labels = map[string]string{}
	}

	info := output.PodInfo{
		Name:   pod.Name,
		Phase:  string(pod.Status.Phase),
		Node:   pod.Spec.NodeName,
		Labels: labels,
	}

	// Owner reference (first one wins — pods usually have a single owner).
	for _, ref := range pod.OwnerReferences {
		if ref.Controller != nil && *ref.Controller {
			info.OwnerKind = ref.Kind
			info.OwnerName = ref.Name
			break
		}
	}

	// Readiness: pod is ready when all containers report ready.
	info.Ready = podReady(pod)

	// Per-container details.
	statusByName := map[string]corev1.ContainerStatus{}
	for _, cs := range pod.Status.ContainerStatuses {
		statusByName[cs.Name] = cs
	}

	var totalRestarts int32
	for _, c := range pod.Spec.Containers {
		cs, ok := statusByName[c.Name]
		ci := output.ContainerInfo{
			Name:  c.Name,
			Image: c.Image,
		}
		if ok {
			ci.Ready = cs.Ready
			ci.RestartCount = cs.RestartCount
			totalRestarts += cs.RestartCount
			ci.State, ci.WaitingReason, ci.TerminatedReason = containerState(cs.State)

			// Previous log tail for crashed containers.
			if cs.LastTerminationState.Terminated != nil {
				code := cs.LastTerminationState.Terminated.ExitCode
				ci.LastExitCode = &code
			}
			needsPrevLogs := cs.RestartCount > 0 ||
				(cs.State.Waiting != nil && isCrashState(cs.State.Waiting.Reason))
			if needsPrevLogs && maxPreviousLines > 0 {
				lines, err := previousLogs(ctx, client, namespace, pod.Name, c.Name, maxPreviousLines)
				if err == nil {
					ci.PreviousLogTail = lines
				}
				// Swallow the error — previous logs failing is non-fatal.
			}
		} else {
			ci.State = "unknown"
		}
		info.Containers = append(info.Containers, ci)
	}
	info.RestartCount = totalRestarts
	return info, nil
}

// podReady returns true when all containers in the pod are ready.
func podReady(pod *corev1.Pod) bool {
	for _, cs := range pod.Status.ContainerStatuses {
		if !cs.Ready {
			return false
		}
	}
	return len(pod.Status.ContainerStatuses) > 0
}

// containerState extracts the state string, waiting reason, and terminated reason.
func containerState(state corev1.ContainerState) (string, string, string) {
	switch {
	case state.Running != nil:
		return "running", "", ""
	case state.Waiting != nil:
		return "waiting", state.Waiting.Reason, ""
	case state.Terminated != nil:
		return "terminated", "", state.Terminated.Reason
	default:
		return "unknown", "", ""
	}
}

// isCrashState returns true for waiting reasons that indicate a crash loop.
func isCrashState(reason string) bool {
	switch reason {
	case "CrashLoopBackOff", "Error", "OOMKilled":
		return true
	default:
		return false
	}
}

// previousLogs fetches the previous (terminated) container log tail.
func previousLogs(
	ctx context.Context,
	client kubernetes.Interface,
	namespace, podName, containerName string,
	tailLines int64,
) ([]string, error) {
	req := client.CoreV1().Pods(namespace).GetLogs(podName, &corev1.PodLogOptions{
		Container: containerName,
		Previous:  true,
		TailLines: &tailLines,
	})
	stream, err := req.Stream(ctx)
	if err != nil {
		return nil, fmt.Errorf("streaming previous logs: %w", err)
	}
	defer stream.Close()

	var buf bytes.Buffer
	if _, err := io.Copy(&buf, stream); err != nil {
		return nil, fmt.Errorf("reading previous logs: %w", err)
	}

	raw := strings.TrimRight(buf.String(), "\n")
	if raw == "" {
		return nil, nil
	}
	return strings.Split(raw, "\n"), nil
}
