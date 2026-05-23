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

func newSummaryCmd(root *rootFlags) *cobra.Command {
	var (
		namespace      string
		app            string
		unit           string
		pod            string
		events         int
		previousLogs   int64
		includeMetrics bool
	)

	cmd := &cobra.Command{
		Use:   "summary",
		Short: "Namespace or workload summary",
		Long: `Collect pod, PVC, event, and metrics diagnostics for a namespace or
Juju workload. Returns a single JSON report with bounded data.

Examples:
  cantrip-kdiag summary --namespace dev --app redis-k8s --format json
  cantrip-kdiag summary --namespace dev --previous-logs 80 --events 40
  cantrip-kdiag summary --namespace dev --pod redis-k8s-0`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return runSummary(root, namespace, app, unit, pod, events, previousLogs, includeMetrics)
		},
	}

	cmd.Flags().StringVarP(&namespace, "namespace", "n", "", "Kubernetes namespace (required)")
	cmd.Flags().StringVar(&app, "app", "", "Filter by Juju application name")
	cmd.Flags().StringVar(&unit, "unit", "", "Filter by Juju unit name (e.g. redis-k8s/0)")
	cmd.Flags().StringVar(&pod, "pod", "", "Filter by exact pod name")
	cmd.Flags().IntVar(&events, "events", 40, "Maximum number of events to include (0 = all)")
	cmd.Flags().Int64Var(&previousLogs, "previous-logs", int64(collect.PreviousLogLines), "Lines of previous container logs to include per crashed container")
	cmd.Flags().BoolVar(&includeMetrics, "include-metrics", false, "Include pod CPU/memory metrics (requires metrics-server)")

	return cmd
}

func runSummary(
	root *rootFlags,
	namespace, app, unit, pod string,
	maxEvents int,
	maxPreviousLogs int64,
	includeMetrics bool,
) error {
	if namespace == "" {
		output.WriteError(os.Stdout, "missing_namespace", "--namespace is required")
		return fmt.Errorf("--namespace is required")
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

	filter := kube.TargetFilter{App: app, Unit: unit, Pod: pod}

	pods, err := collect.Pods(ctx, cs.Core, namespace, filter, maxPreviousLogs)
	if err != nil {
		output.WriteError(os.Stdout, "api_error", err.Error())
		os.Exit(kube.ExitAPIUnreachable)
	}

	eventsData, err := collect.Events(ctx, cs.Core, namespace, maxEvents)
	if err != nil {
		output.WriteError(os.Stdout, "api_error", err.Error())
		os.Exit(kube.ExitAPIUnreachable)
	}

	pvcs, err := collect.PVCs(ctx, cs.Core, namespace, filter)
	if err != nil {
		output.WriteError(os.Stdout, "api_error", err.Error())
		os.Exit(kube.ExitAPIUnreachable)
	}

	metricsAvailable := false
	if includeMetrics && cs.Metrics != nil {
		metricsMap, available, _ := collect.Metrics(ctx, cs.Metrics, namespace)
		if available {
			metricsAvailable = true
			collect.AnnotatePods(pods, metricsMap)
		}
	}

	warnings := summarise.Warnings(pods, pvcs, eventsData)
	stats := summarise.Stats(pods, pvcs, eventsData)

	// Determine the effective context name.
	effectiveContext := root.Context
	if effectiveContext == "" {
		effectiveContext = "<default>"
	}

	var appPtr, unitPtr, podPtr *string
	if app != "" {
		appPtr = &app
	}
	if unit != "" {
		unitPtr = &unit
	}
	if pod != "" {
		podPtr = &pod
	}

	report := output.Report{
		SchemaVersion:    output.SchemaVersion,
		GeneratedAt:      time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		Context:          output.ContextInfo{KubeconfigPath: kubeconfigPath, Context: effectiveContext, Namespace: namespace},
		Query:            output.QueryInfo{App: appPtr, Unit: unitPtr, Pod: podPtr},
		MetricsAvailable: metricsAvailable,
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

// errorCode maps an exit code integer to a machine-friendly string.
func errorCode(code int) string {
	switch code {
	case kube.ExitKubeconfigMissing:
		return "kubeconfig_missing"
	case kube.ExitContextInvalid:
		return "context_not_found"
	case kube.ExitAPIUnreachable:
		return "api_unreachable"
	case kube.ExitTargetNotFound:
		return "target_not_found"
	case kube.ExitMetricsUnavailable:
		return "metrics_unavailable"
	default:
		return "internal_error"
	}
}
