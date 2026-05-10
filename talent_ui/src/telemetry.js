import { ApplicationInsights } from "@microsoft/applicationinsights-web";

let appInsights = null;

const connStr = import.meta.env.VITE_APPINSIGHTS_CONNECTION_STRING;
if (connStr) {
  try {
    appInsights = new ApplicationInsights({
      config: {
        connectionString: connStr,
        enableAutoRouteTracking: true,
        disableFetchTracking: false,
      },
    });
    appInsights.loadAppInsights();
  } catch {
    appInsights = null;
  }
}

export function trackUserQuery(query, backend) {
  appInsights?.trackEvent({ name: "UserQuery" }, { query: query?.substring(0, 200), backend });
}

export function trackApiCallStart(endpoint) {
  const start = Date.now();
  return {
    complete(status) {
      appInsights?.trackDependencyData({
        id: crypto.randomUUID?.() || String(start),
        target: endpoint,
        name: endpoint,
        duration: Date.now() - start,
        success: status < 400,
        resultCode: status,
        type: "HTTP",
      });
    },
    fail(error) {
      appInsights?.trackDependencyData({
        id: crypto.randomUUID?.() || String(start),
        target: endpoint,
        name: endpoint,
        duration: Date.now() - start,
        success: false,
        resultCode: 0,
        type: "HTTP",
        data: error?.message,
      });
    },
  };
}

export function trackQueryResponseTime(query, backend, duration, success) {
  appInsights?.trackMetric({ name: "QueryResponseTime", average: duration }, { query: query?.substring(0, 200), backend, success: String(success) });
}

export function trackWorkflowEvent(type, properties) {
  appInsights?.trackEvent({ name: `Workflow_${type}` }, properties);
}

export function trackError(error, properties) {
  if (appInsights) {
    appInsights.trackException({ exception: error instanceof Error ? error : new Error(String(error)) }, properties);
  }
}

export function trackEvent(name, properties) {
  appInsights?.trackEvent({ name }, properties);
}
