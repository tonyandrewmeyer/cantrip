package output

import (
	"encoding/json"
	"fmt"
	"io"
)

// WriteJSON encodes v as indented JSON to w.
func WriteJSON(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

// WriteError encodes an ErrorResponse as indented JSON to w and returns the
// error so callers can propagate it after printing.
func WriteError(w io.Writer, code, message string) {
	resp := ErrorResponse{
		SchemaVersion: SchemaVersion,
		Error: ErrorDetail{
			Code:    code,
			Message: message,
		},
	}
	// Best-effort — if we can't write to stdout the caller will see the exit
	// code and the empty output, which is still actionable.
	_ = WriteJSON(w, resp)
}

// TextReport renders a Report as human-friendly text.
func TextReport(w io.Writer, r *Report) {
	fmt.Fprintf(w, "Namespace: %s  Context: %s\n", r.Context.Namespace, r.Context.Context)
	fmt.Fprintf(w, "Pods: %d total, %d ready, %d restarting\n",
		r.Summary.PodCount, r.Summary.ReadyPods, r.Summary.RestartingPods)
	if r.Summary.WarningEventCount > 0 {
		fmt.Fprintf(w, "Warning events: %d\n", r.Summary.WarningEventCount)
	}
	if r.Summary.PVCPendingCount > 0 {
		fmt.Fprintf(w, "PVCs pending: %d\n", r.Summary.PVCPendingCount)
	}
	for _, w2 := range r.Warnings {
		fmt.Fprintf(w, "  ! %s\n", w2)
	}
	for _, pod := range r.Pods {
		readyStr := "ready"
		if !pod.Ready {
			readyStr = "not-ready"
		}
		fmt.Fprintf(w, "\nPod %s  phase=%s  %s  restarts=%d\n",
			pod.Name, pod.Phase, readyStr, pod.RestartCount)
		for _, c := range pod.Containers {
			fmt.Fprintf(w, "  container %s: %s", c.Name, c.State)
			if c.WaitingReason != "" {
				fmt.Fprintf(w, " (%s)", c.WaitingReason)
			}
			if c.TerminatedReason != "" {
				fmt.Fprintf(w, " terminated=%s", c.TerminatedReason)
			}
			fmt.Fprintln(w)
			for _, line := range c.PreviousLogTail {
				fmt.Fprintf(w, "    %s\n", line)
			}
		}
	}
}
