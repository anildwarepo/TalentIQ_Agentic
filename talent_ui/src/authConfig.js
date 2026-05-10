// Entra ID configuration for TalentIQ SPA
//
// Register as SPA platform with redirect URI: http://localhost:5173
// Grant delegated permission: https://ai.azure.com/user_impersonation

export const msalConfig = {
  auth: {
    clientId: "48449491-8390-4af0-8121-da7af091ad56",
    authority: "https://login.microsoftonline.com/150305b3-cc4b-46dd-9912-425678db1498",
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
};

// Foundry scope — token is forwarded to backend → Foundry Agent
export const foundryLoginRequest = {
  scopes: ["https://ai.azure.com/user_impersonation"],
};
