#!/usr/bin/env python3
# ruff: noqa: E501, I001
"""Patch a Hermes3D checkout with read-only analytics support for custom runtimes.

The upstream custom runtime seam can hydrate agents from HTTP /health, /state and
/registry, but the native Analytics panel calls GatewayClient directly for
`sessions.usage` and `usage.cost`.  A custom HTTP runtime therefore renders its
agents successfully while Analytics fails with "Gateway is not connected.".

This patch keeps the gateway connection semantics unchanged.  It only routes
Analytics through the active RuntimeProvider when the active adapter is
`custom`, and adds zero-cost, read-only compatibility implementations for the
two analytics RPCs on CustomRuntimeProvider.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "AI_TRADING_BTC_CUSTOM_ANALYTICS_PATCH"


def replace_once(path: Path, old: str, new: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_provider(root: Path) -> bool:
    path = root / "src/lib/runtime/custom/provider.ts"
    changed = False
    changed |= replace_once(
        path,
        '      case "sessions.list":\n        return (await this.callSessionsList(params)) as T;\n',
        '      case "sessions.list":\n        return (await this.callSessionsList(params)) as T;\n'
        '      case "sessions.usage":\n        return (await this.callSessionsUsage(params)) as T;\n'
        '      case "usage.cost":\n        return (await this.callUsageCost(params)) as T;\n',
        "custom provider analytics dispatch",
    )

    methods = f'''  // {MARKER}: native Hermes3D Analytics compatibility for HTTP custom runtimes.\n  private async callSessionsUsage(_rawParams: unknown) {{\n    const descriptor = await this.describeRuntime();\n    const runtimeName = descriptor.metadata.runtimeName ?? this.metadata.runtimeName ?? "Custom Runtime";\n    const modelChoices = normalizeModelChoices(descriptor.registry);\n    const agents = buildSyntheticAgents(descriptor.state, runtimeName);\n    const zeroTotals = {{\n      input: 0,\n      output: 0,\n      cacheRead: 0,\n      cacheWrite: 0,\n      totalTokens: 0,\n      totalCost: 0,\n      inputCost: 0,\n      outputCost: 0,\n      cacheReadCost: 0,\n      cacheWriteCost: 0,\n      durationMs: 0,\n    }};\n\n    const sessions = agents.map((agent) => {{\n      const session = this.ensureSession(\n        agent.id,\n        agent.id,\n        resolveDefaultModelId(descriptor.state, modelChoices)\n      );\n      const userMessages = session.messages.filter((message) => message.role === "user").length;\n      const assistantMessages = session.messages.filter((message) => message.role === "assistant").length;\n      return {{\n        key: session.sessionKey,\n        label: agent.name,\n        agentId: agent.id,\n        channel: "custom-runtime",\n        modelProvider: "custom",\n        model: session.model,\n        updatedAt: session.updatedAt,\n        usage: {{\n          ...zeroTotals,\n          messageCounts: {{\n            total: session.messages.length,\n            user: userMessages,\n            assistant: assistantMessages,\n            toolCalls: 0,\n            toolResults: 0,\n            errors: 0,\n          }},\n          toolUsage: {{ totalCalls: 0, tools: [] }},\n          modelUsage: session.model\n            ? [{{ provider: "custom", model: session.model, count: session.messages.length, totals: zeroTotals }}]\n            : [],\n          dailyBreakdown: [],\n          dailyMessageCounts: [],\n        }},\n      }};\n    }});\n\n    return {{ sessions, totals: zeroTotals, aggregates: {{}} }};\n  }}\n\n  private async callUsageCost(_rawParams: unknown) {{\n    // Trading runtime observation is read-only and has no LLM billing contract.\n    // Returning an empty cost series keeps native Hermes3D Analytics truthful.\n    return {{ daily: [] }};\n  }}\n\n'''
    changed |= replace_once(
        path,
        "  private async callSessionsPreview(rawParams: unknown) {\n",
        methods + "  private async callSessionsPreview(rawParams: unknown) {\n",
        "custom provider analytics methods",
    )
    return changed


def patch_usage_hook(root: Path) -> bool:
    path = root / "src/features/office/hooks/useUsageAnalytics.ts"
    return replace_once(
        path,
        "  client: GatewayClient;\n  status: GatewayStatus;\n",
        '  client: Pick<GatewayClient, "call">;\n  status: GatewayStatus;\n',
        "usage analytics call-only client type",
    )


def patch_view_model(root: Path) -> bool:
    path = root / "src/features/office/hooks/useOfficeUsageAnalyticsViewModel.ts"
    return replace_once(
        path,
        "  client: GatewayClient;\n  status: GatewayStatus;\n",
        '  client: Pick<GatewayClient, "call">;\n  status: GatewayStatus;\n',
        "analytics view-model call-only client type",
    )


def patch_analytics_panel(root: Path) -> bool:
    path = root / "src/features/office/components/panels/AnalyticsPanel.tsx"
    changed = False
    changed |= replace_once(
        path,
        "export function AnalyticsPanel({\n  client,\n  status,\n",
        "export function AnalyticsPanel({\n  client,\n  analyticsClient,\n  status,\n  analyticsStatus,\n",
        "analytics panel destructuring",
    )
    changed |= replace_once(
        path,
        "  client: GatewayClient;\n  status: GatewayStatus;\n",
        '  client: GatewayClient;\n  analyticsClient?: Pick<GatewayClient, "call">;\n  status: GatewayStatus;\n  analyticsStatus?: GatewayStatus;\n',
        "analytics panel props",
    )
    changed |= replace_once(
        path,
        "  } = useOfficeUsageAnalyticsViewModel({\n    client,\n    status,\n",
        "  } = useOfficeUsageAnalyticsViewModel({\n    client: analyticsClient ?? client,\n    status: analyticsStatus ?? status,\n",
        "analytics panel provider routing",
    )
    return changed


def patch_office_screen(root: Path) -> bool:
    path = root / "src/features/office/screens/OfficeScreen.tsx"
    return replace_once(
        path,
        "            <AnalyticsPanel\n              client={client}\n              status={status}\n",
        "            <AnalyticsPanel\n              client={client}\n              analyticsClient={provider}\n              status={status}\n              analyticsStatus={\n                activeAdapterType === \"custom\" && state.agents.length > 0\n                  ? \"connected\"\n                  : status\n              }\n",
        "office analytics custom runtime routing",
    )


def apply(root: Path) -> int:
    root = root.resolve()
    required = [
        root / "src/lib/runtime/custom/provider.ts",
        root / "src/features/office/hooks/useUsageAnalytics.ts",
        root / "src/features/office/hooks/useOfficeUsageAnalyticsViewModel.ts",
        root / "src/features/office/components/panels/AnalyticsPanel.tsx",
        root / "src/features/office/screens/OfficeScreen.tsx",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Hermes3D checkout is incomplete; missing: " + ", ".join(missing))

    changes = [
        patch_provider(root),
        patch_usage_hook(root),
        patch_view_model(root),
        patch_analytics_panel(root),
        patch_office_screen(root),
    ]
    count = sum(changes)
    print(f"Hermes3D custom analytics patch complete: {count} file(s) changed")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Hermes3D checkout root (default: current directory)",
    )
    args = parser.parse_args()
    apply(Path(args.root))


if __name__ == "__main__":
    main()
