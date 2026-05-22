import React from "react";
import ReactDOM from "react-dom/client";
import { PublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { msalConfig } from "./authConfig";
import App from "./App";

// Demo / partial-environment auth bypass.
// When VITE_DISABLE_AUTH=true (set at Docker build time by
// talent_infra_modules/03-frontend/deploy.ps1), MSAL is skipped entirely:
// no PublicClientApplication is created, no MsalProvider wraps the tree.
// App.jsx synthesizes an authenticated demo user in this mode.
// See talent_infra_modules/AUTH-DISABLED.md for the full contract.
const AUTH_DISABLED = import.meta.env.VITE_DISABLE_AUTH === "true";

const root = ReactDOM.createRoot(document.getElementById("root"));

if (AUTH_DISABLED) {
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} else {
  const msalInstance = new PublicClientApplication(msalConfig);
  root.render(
    <React.StrictMode>
      <MsalProvider instance={msalInstance}>
        <App />
      </MsalProvider>
    </React.StrictMode>
  );
}
