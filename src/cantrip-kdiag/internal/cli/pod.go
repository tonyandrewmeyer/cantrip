package cli

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/spf13/cobra"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/collect"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/summarise"
)

func newPodCmd(root *rootFlags) *cobra.Command {
	var (
		namespace    string
		pod          string
		previousLogs int64
	)

	cmd := &cobra.Command{
		Use:   "pod",
		Short: "Detailed diagnostics for a specific pod",
		Long: `Collect container statuses, events, and previous log tails for a
specific pod. Returns a single JSON report.

Examples:
  cantrip-kdiag pod --namespace dev --pod redis-k8s-0
  cantrip-kdiag pod --namespace dev --pod redis-k8s-0 --previous-logs 120`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return runPod(root, namespace, pod, previousLogs)
		},
	}

	cmd.Flags().StringVarP(&namespace, "namespace", "n", "", "Kubernetes namespace (required)")
	cmd.Flags().StringVar(&pod, "pod", "", "Pod name (required)")
	cmd.Flags().Int64Var(&previousLogs, "previous-logs", int64(collect.PreviousLogLines), "Lines of previous container logs per crashed container")

	return cmd
}

func runPod(root *rootFlags, namespace, podName string, maxPreviousLogs int64) error {
	if namespace == "" {
		output.WriteError(os.Stdout, "missing_namespace", "--namespace is required")
		return fmt.Errorf("--namespace is required")
	}
	if podName == "" {
		output.WriteError(os.Stdout, "missing_pod", "--pod is required")
		return fmt.Errorf("--pod is required")
	}

	kubeconfigPath := kube.KubeconfigPath(root.Kubeconfig)
	ctx, cancel := context.WithTimeout(context.Background(), root.Timeout)
	defer cancel()

	cs, err := kube.NewClientSet(kubeconfigPath, root.Context)
	if err != nil {
		ke, ok := err.(*kube.KubeconfigError)
		if ok {
			output.WriteError(os.Stdout, errorCode(ke.Code), ke.Message)
			os.Exit(ke.Code)
		}
		output.WriteError(os.Stdout, "internal_error", err.Error())
		os.Exit(kube.ExitInternalError)
	}

	podInfo, err := collect.SinglePod(ctx, cs.Core, namespace, podName, maxPreviousLogs)
	if err != nil {
		output.WriteError(os.Stdout, "target_not_found", err.Error())
		os.Exit(kube.ExitTargetNotFound)
	}

	eventsData, err := collect.Events(ctx, cs.Core, namespace, 40)
	if err != nil {
		output.WriteError(os.Stdout, "api_error", err.Error())
		os.Exit(kube.ExitAPIUnreachable)
	}

	filter := kube.TargetFilter{Pod: podName}
	pvcs, err := collect.PVCs(ctx, cs.Core, namespace, filter)
	if err != nil {
		output.WriteError(os.Stdout, "api_error", err.Error())
		os.Exit(kube.ExitAPIUnreachable)
	}

	pods := []output.PodInfo{podInfo}
	warnings := summarise.Warnings(pods, pvcs, eventsData)
	stats := summarise.Stats(pods, pvcs, eventsData)

	effectiveContext := root.Context
	if effectiveContext == "" {
		effectiveContext = "<default>"
	}
	podNameCopy := podName

	report := output.Report{
		SchemaVersion:    output.SchemaVersion,
		GeneratedAt:      time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		Context:          output.ContextInfo{KubeconfigPath: kubeconfigPath, Context: effectiveContext, Namespace: namespace},
		Query:            output.QueryInfo{Pod: &podNameCopy},
		MetricsAvailable: false,
		Pods:             pods,
		PVCs:             pvcs,
		Events:           eventsData,
		Warnings:         warnings,
		Summary:          stats,
	}

	if root.Format == "text" {
		output.TextReport(os.Stdout, &report)
		return nil
	}
	return output.WriteJSON(os.Stdout, report)
}
