import { useEffect, useState } from "react";
import { DbConnection } from "./module_bindings";
import type {
  QueryResult,
  Shop,
  ShopInvite,
  UserProfile,
  VisionQuery,
} from "./module_bindings/types";

export type UserRole = "admin" | "worker" | "personal";

export type SavedAccount = {
  identityHex: string;
  token: string;
  label: string;
  role?: string;
};

const TOKEN_STORAGE_KEY = "carvis_spacetimedb_token";
const SAVED_ACCOUNTS_KEY = "carvis_spacetimedb_accounts";

const SPACETIMEDB_URI =
  import.meta.env.VITE_SPACETIMEDB_URI || "https://maincloud.spacetimedb.com";
const SPACETIMEDB_DB_NAME =
  import.meta.env.VITE_SPACETIMEDB_DB_NAME || "hackutd";
const SPACETIMEAUTH_CLIENT_ID =
  import.meta.env.VITE_SPACETIMEAUTH_CLIENT_ID || "";

export type SpacetimeState = {
  connected: boolean;
  connecting: boolean;
  error: string;
  identityHex: string;
  token: string;
  profile: UserProfile | null;
  shop: Shop | null;
  members: UserProfile[];
  calls: VisionQuery[];
  results: Record<string, QueryResult>;
  invites: ShopInvite[];
  savedAccounts: SavedAccount[];
};

let activeConnection: DbConnection | null = null;

function loadSavedAccounts(): SavedAccount[] {
  try {
    const raw = localStorage.getItem(SAVED_ACCOUNTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveAccountToStorage(
  identityHex: string,
  token: string,
  label?: string,
  role?: string
): SavedAccount[] {
  const existing = loadSavedAccounts();
  const idx = existing.findIndex((a) => a.identityHex === identityHex);
  const entry: SavedAccount = {
    identityHex,
    token,
    label: label || existing[idx]?.label || `Account ${identityHex.slice(0, 6)}`,
    role: role || existing[idx]?.role,
  };
  const updated =
    idx >= 0
      ? existing.map((item, i) => (i === idx ? entry : item))
      : [entry, ...existing];
  try {
    localStorage.setItem(SAVED_ACCOUNTS_KEY, JSON.stringify(updated));
  } catch {
    // Ignore storage quota errors
  }
  return updated;
}

function captureTokenFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const queryParams = new URLSearchParams(window.location.search);
  const urlToken =
    hashParams.get("id_token") ||
    hashParams.get("token") ||
    queryParams.get("id_token") ||
    queryParams.get("token");

  if (urlToken) {
    localStorage.setItem(TOKEN_STORAGE_KEY, urlToken);
    const cleanUrl = window.location.origin + window.location.pathname;
    window.history.replaceState({}, document.title, cleanUrl);
    return urlToken;
  }
  return null;
}

let state: SpacetimeState = {
  connected: false,
  connecting: false,
  error: "",
  identityHex: "",
  token: "",
  profile: null,
  shop: null,
  members: [],
  calls: [],
  results: {},
  invites: [],
  savedAccounts: typeof window !== "undefined" ? loadSavedAccounts() : [],
};

const listeners = new Set<() => void>();

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function setState(patch: Partial<SpacetimeState>) {
  state = { ...state, ...patch };
  emitChange();
}

function syncCacheFromConnection(conn: DbConnection) {
  const profiles = [...conn.db.myProfile.iter()];
  const profile = profiles[0] ?? null;

  const shops = [...conn.db.myShop.iter()];
  const shop = shops[0] ?? null;

  const members = [...conn.db.shopMembers.iter()].sort((a, b) =>
    a.name.localeCompare(b.name)
  );

  const calls = [...conn.db.shopCalls.iter()].sort((a, b) => {
    const aTime = a.createdAt?.microsSinceUnixEpoch ?? 0n;
    const bTime = b.createdAt?.microsSinceUnixEpoch ?? 0n;
    return bTime > aTime ? 1 : bTime < aTime ? -1 : 0;
  });

  const results: Record<string, QueryResult> = {};
  for (const r of conn.db.shopCallResults.iter()) {
    results[r.queryId] = r;
  }

  const invites = [...conn.db.visibleInvites.iter()].sort((a, b) => {
    const aTime = a.createdAt?.microsSinceUnixEpoch ?? 0n;
    const bTime = b.createdAt?.microsSinceUnixEpoch ?? 0n;
    return bTime > aTime ? 1 : bTime < aTime ? -1 : 0;
  });

  let savedAccounts = state.savedAccounts;
  if (profile && state.identityHex && state.token) {
    savedAccounts = saveAccountToStorage(
      state.identityHex,
      state.token,
      profile.name,
      profile.role
    );
  }

  setState({
    profile,
    shop,
    members,
    calls,
    results,
    invites,
    savedAccounts,
  });
}

function attachTableListeners(conn: DbConnection) {
  const refresh = () => syncCacheFromConnection(conn);

  conn.db.myProfile.onInsert(refresh);
  conn.db.myProfile.onUpdate(refresh);
  conn.db.myProfile.onDelete(refresh);

  conn.db.myShop.onInsert(refresh);
  conn.db.myShop.onUpdate(refresh);
  conn.db.myShop.onDelete(refresh);

  conn.db.shopMembers.onInsert(refresh);
  conn.db.shopMembers.onUpdate(refresh);
  conn.db.shopMembers.onDelete(refresh);

  conn.db.shopCalls.onInsert(refresh);
  conn.db.shopCalls.onUpdate(refresh);
  conn.db.shopCalls.onDelete(refresh);

  conn.db.shopCallResults.onInsert(refresh);
  conn.db.shopCallResults.onUpdate(refresh);
  conn.db.shopCallResults.onDelete(refresh);

  conn.db.visibleInvites.onInsert(refresh);
  conn.db.visibleInvites.onUpdate(refresh);
  conn.db.visibleInvites.onDelete(refresh);
}

export function connectSpacetime(overrideToken?: string | null) {
  if (activeConnection) {
    try {
      activeConnection.disconnect();
    } catch {
      // ignore disconnect error
    }
    activeConnection = null;
  }

  const urlToken = captureTokenFromUrl();
  const storedToken =
    overrideToken !== undefined
      ? overrideToken || undefined
      : urlToken || localStorage.getItem(TOKEN_STORAGE_KEY) || undefined;

  setState({
    connecting: true,
    connected: false,
    error: "",
    profile: null,
    shop: null,
    members: [],
    calls: [],
    results: {},
    invites: [],
  });

  try {
    const conn = DbConnection.builder()
      .withUri(SPACETIMEDB_URI)
      .withDatabaseName(SPACETIMEDB_DB_NAME)
      .withToken(storedToken)
      .withAutomaticReconnect()
      .onConnect((connection, identity, token) => {
        const identityHex = identity.toHexString().toLowerCase();
        localStorage.setItem(TOKEN_STORAGE_KEY, token);
        const savedAccounts = saveAccountToStorage(identityHex, token);

        setState({
          connected: true,
          connecting: false,
          error: "",
          identityHex,
          token,
          savedAccounts,
        });

        attachTableListeners(connection);

        connection
          .subscriptionBuilder()
          .onApplied(() => {
            syncCacheFromConnection(connection);
          })
          .onError((_ctx) => {
            setState({
              error: "Subscription error while syncing SpacetimeDB views.",
            });
          })
          .subscribeToAllTables();
      })
      .onConnectError((_ctx, err) => {
        setState({
          connected: false,
          connecting: false,
          error: err.message || "Could not connect to SpacetimeDB.",
        });
      })
      .onDisconnect((_ctx, err) => {
        setState({
          connected: false,
          connecting: false,
          error: err ? err.message : "",
        });
      })
      .build();

    activeConnection = conn;
  } catch (err) {
    setState({
      connected: false,
      connecting: false,
      error:
        err instanceof Error
          ? err.message
          : "Failed to initialize SpacetimeDB connection.",
    });
  }
}

export function createNewSpacetimeIdentity() {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  connectSpacetime(null);
}

export function switchSpacetimeAccount(token: string) {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
  connectSpacetime(token);
}

export function startSpacetimeAuthOidc() {
  if (!SPACETIMEAUTH_CLIENT_ID) {
    createNewSpacetimeIdentity();
    return;
  }
  const redirectUri = encodeURIComponent(
    window.location.origin + window.location.pathname
  );
  const nonce = crypto.randomUUID();
  const authUrl =
    `https://auth.spacetimedb.com/authorize?client_id=${encodeURIComponent(
      SPACETIMEAUTH_CLIENT_ID
    )}` +
    `&redirect_uri=${redirectUri}` +
    `&response_type=id_token` +
    `&scope=openid%20profile%20email` +
    `&nonce=${encodeURIComponent(nonce)}`;
  window.location.href = authUrl;
}

export const spacetimeActions = {
  async registerOrUpdateProfile(params: {
    name: string;
    email: string;
    requestedRole: UserRole;
    shopName: string;
  }) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.registerOrUpdateProfile(params);
  },

  async inviteWorker(targetIdentityOrEmail: string) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.inviteWorker({ targetIdentityOrEmail });
  },

  async acceptInvite(inviteId: bigint) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.acceptInvite({ inviteId });
  },

  async declineInvite(inviteId: bigint) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.declineInvite({ inviteId });
  },

  async joinShopByCode(inviteCode: string) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.joinShopByCode({ inviteCode });
  },

  async revokeInvite(inviteId: bigint) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.revokeInvite({ inviteId });
  },

  async removeShopWorker(workerIdentityHex: string) {
    if (!activeConnection) throw new Error("Not connected to SpacetimeDB.");
    await activeConnection.reducers.removeShopWorker({ workerIdentityHex });
  },

  async startShopQuery(params: {
    queryId: string;
    sessionId: string;
    vehicleYear: string;
    vehicleMake: string;
    vehicleModel: string;
    question: string;
  }) {
    if (!activeConnection) return;
    await activeConnection.reducers.startShopQuery(params);
  },

  async recordShopQueryResult(params: {
    queryId: string;
    component: string;
    confidence: number;
    status: string;
    answer: string;
    sourceRef: string;
    sourceGrounded: boolean;
    latencyMs: number;
  }) {
    if (!activeConnection) return;
    await activeConnection.reducers.recordShopQueryResult(params);
  },
};

export function useSpacetime(): SpacetimeState {
  const [snap, setSnap] = useState<SpacetimeState>(state);

  useEffect(() => {
    const listener = () => setSnap(state);
    listeners.add(listener);
    if (!activeConnection && !state.connecting) {
      connectSpacetime();
    }
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return snap;
}
