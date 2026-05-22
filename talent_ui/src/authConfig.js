// Entra ID configuration for TalentIQ SPA
//
// Register as SPA platform with redirect URI: http://localhost:5173
// Grant delegated permission: https://ai.azure.com/user_impersonation
//
// When VITE_DISABLE_AUTH=true (see talent_infra_modules/AUTH-DISABLED.md),
// this module is still imported by main.jsx but `msalConfig` is exported as
// `null` and no PublicClientApplication is constructed — avoids console
// errors about missing clientId in demo deployments without an app reg.

const AUTH_DISABLED = import.meta.env.VITE_DISABLE_AUTH === "true";

const clientId =
  import.meta.env.VITE_MSAL_CLIENT_ID || "48449491-8390-4af0-8121-da7af091ad56";
const authority =
  import.meta.env.VITE_MSAL_AUTHORITY ||
  "https://login.microsoftonline.com/150305b3-cc4b-46dd-9912-425678db1498";
const redirectUri =
  import.meta.env.VITE_MSAL_REDIRECT_URI ||
  (typeof window !== "undefined" ? window.location.origin : "/");

export const msalConfig = AUTH_DISABLED
  ? null
  : {
      auth: {
        clientId,
        authority,
        redirectUri,
        postLogoutRedirectUri: redirectUri,
      },
      cache: {
        cacheLocation: "sessionStorage",
        storeAuthStateInCookie: false,
      },
    };

// Foundry scope — token is forwarded to backend → Foundry Agent
export const foundryLoginRequest = {
  scopes: [
    import.meta.env.VITE_FOUNDRY_API_SCOPE ||
      "https://ai.azure.com/user_impersonation",
  ],
};
