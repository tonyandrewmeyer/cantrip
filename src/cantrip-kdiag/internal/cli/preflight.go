package cli

import (
	"context"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/collect"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func newPreflightCmd(root *rootFlags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "preflight",
		Short: "Check kubeconfig, context, and API reachability",
		Long: `Quickly verify that the kubeconfig is readable, the selected context
exists, and the API server is reachable. Optionally checks whether the
metrics API is available.

Examples:
  cantrip-kdiag preflight --context my-cluster --format json
  cantrip-kdiag preflight`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return runPreflight(root)
		},
	}
	return cmd
}

func runPreflight(root *rootFlags) error {
	kubeconfigPath := kube.KubeconfigPath(root.Kubeconfig)

	cs, err := kube.NewClientSet(kubeconfigPath, root.Context)
	if err != nil {
		ke, ok := err.(*kube.KubeconfigError)
		if ok {
			if root.Format == "json" {
				output.WriteError(os.Stdout, errorCode(ke.Code), ke.Message)
			} else {
				fmt.Fprintf(os.Stderr, "error: %s\n", ke.Message)
			}
			os.Exit(ke.Code)
		}
		output.WriteError(os.Stdout, "internal_error", err.Error())
		os.Exit(kube.ExitInternalError)
	}

	ctx, cancel := context.WithTimeout(context.Background(), root.Timeout)
	defer cancel()

	// Probe API reachability with a cheap server-version call.
	_, apiErr := cs.Core.CoreV1().Namespaces().List(ctx, metav1.ListOptions{Limit: 1})
	apiReachable := apiErr == nil

	// Probe metrics availability.
	metricsAvailable := false
	if apiReachable {
		_, available, _ := collect.Metrics(ctx, cs.Metrics, "default")
		metricsAvailable = available
	}

	effectiveContext := root.Context
	if effectiveContext == "" {
		effectiveContext = "<default>"
	}

	report := output.PreflightReport{
		SchemaVersion:    output.SchemaVersion,
		KubeconfigPath:   kubeconfigPath,
		Context:          effectiveContext,
		APIReachable:     apiReachable,
		MetricsAvailable: metricsAvailable,
	}

	if root.Format == "text" {
		fmt.Fprintf(os.Stdout, "kubeconfig: %s\n", report.KubeconfigPath)
		fmt.Fprintf(os.Stdout, "context:    %s\n", report.Context)
		fmt.Fprintf(os.Stdout, "api:        ")
		if apiReachable {
			fmt.Fprintln(os.Stdout, "reachable")
		} else {
			fmt.Fprintln(os.Stdout, "unreachable")
		}
		fmt.Fprintf(os.Stdout, "metrics:    ")
		if metricsAvailable {
			fmt.Fprintln(os.Stdout, "available")
		} else {
			fmt.Fprintln(os.Stdout, "unavailable")
		}
		return nil
	}

	if err := output.WriteJSON(os.Stdout, report); err != nil {
		return fmt.Errorf("writing preflight JSON: %w", err)
	}
	if !apiReachable {
		os.Exit(kube.ExitAPIUnreachable)
	}
	return nil
}
