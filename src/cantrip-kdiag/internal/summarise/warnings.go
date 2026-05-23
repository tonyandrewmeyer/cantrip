// Package summarise synthesises warning strings and assembles the final report.
package summarise

import (
	"fmt"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
)

// Warnings builds a deterministic list of machine-friendly warning strings
// from the pods, PVCs, and events in the report.  The list is designed to
// help the Python tool produce a concise caption without further parsing.
func Warnings(pods []output.PodInfo, pvcs []output.PVCInfo, events []output.EventInfo) []string {
	var warnings []string

	for _, pod := range pods {
		for _, c := range pod.Containers {
			if c.WaitingReason != "" {
				warnings = append(warnings,
					fmt.Sprintf("pod %s container %s waiting: %s", pod.Name, c.Name, c.WaitingReason))
			}
			if c.TerminatedReason != "" && c.TerminatedReason != "Completed" {
				warnings = append(warnings,
					fmt.Sprintf("pod %s container %s last termination: %s", pod.Name, c.Name, c.TerminatedReason))
			}
		}
	}

	for _, pvc := range pvcs {
		if pvc.Phase == "Pending" || pvc.Phase == "Lost" {
			warnings = append(warnings,
				fmt.Sprintf("pvc %s phase %s", pvc.Name, pvc.Phase))
		}
	}

	for _, ev := range events {
		if ev.Type == "Warning" {
			warnings = append(warnings,
				fmt.Sprintf("warning event %s for %s: %s", ev.Reason, ev.InvolvedObject, ev.Message))
		}
	}

	if warnings == nil {
		warnings = []string{}
	}
	return warnings
}

// Stats computes the summary statistics from the collected report data.
func Stats(pods []output.PodInfo, pvcs []output.PVCInfo, events []output.EventInfo) output.SummaryStats {
	stats := output.SummaryStats{
		PodCount: len(pods),
	}
	for _, pod := range pods {
		if pod.Ready {
			stats.ReadyPods++
		}
		if pod.RestartCount > 0 {
			stats.RestartingPods++
		}
	}
	for _, pvc := range pvcs {
		if pvc.Phase == "Pending" {
			stats.PVCPendingCount++
		}
	}
	for _, ev := range events {
		if ev.Type == "Warning" {
			stats.WarningEventCount++
		}
	}
	return stats
}
