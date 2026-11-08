import {
  schema,
  table,
  t,
  SenderError,
  type Infer,
  type InferSchema,
  type ReducerCtx,
} from 'spacetimedb/server';

const userProfile = table(
  { name: 'user_profile' },
  {
    identity: t.identity().primaryKey(),
    identityHex: t.string().unique(),
    email: t.string().index('btree'),
    name: t.string(),
    role: t.string(), // 'admin' | 'worker' | 'personal'
    shopId: t.string().index('btree'), // '' for personal users
    createdAt: t.timestamp(),
    lastSeenAt: t.timestamp(),
  }
);

const shop = table(
  { name: 'shop' },
  {
    id: t.string().primaryKey(),
    name: t.string(),
    inviteCode: t.string().unique(),
    ownerIdentity: t.identity().index('btree'),
    ownerName: t.string(),
    createdAt: t.timestamp(),
  }
);

const shopInvite = table(
  { name: 'shop_invite' },
  {
    inviteId: t.u64().primaryKey().autoInc(),
    shopId: t.string().index('btree'),
    shopName: t.string(),
    invitedByIdentity: t.identity(),
    invitedByName: t.string(),
    invitedIdentityHex: t.string().index('btree'),
    invitedEmail: t.string().index('btree'),
    status: t.string(), // 'pending' | 'accepted' | 'declined' | 'revoked'
    createdAt: t.timestamp(),
  }
);

const visionQuery = table(
  { name: 'vision_query' },
  {
    id: t.string().primaryKey(),
    sessionId: t.string().index('btree'),
    shopId: t.string().index('btree'),
    callerIdentity: t.identity().index('btree'),
    callerName: t.string(),
    callerRole: t.string(), // 'admin' | 'worker'
    vehicleYear: t.string(),
    vehicleMake: t.string(),
    vehicleModel: t.string(),
    question: t.string(),
    component: t.string(),
    confidence: t.f64(),
    status: t.string(), // 'captured' | 'identifying' | 'retrieving' | 'answered' | 'refused' | 'failed'
    createdAt: t.timestamp(),
    updatedAt: t.timestamp(),
  }
);

const queryResult = table(
  { name: 'query_result' },
  {
    queryId: t.string().primaryKey(),
    shopId: t.string().index('btree'),
    callerIdentity: t.identity().index('btree'),
    callerName: t.string(),
    answer: t.string(),
    sourceRef: t.string(),
    sourceGrounded: t.bool(),
    latencyMs: t.u32(),
    createdAt: t.timestamp(),
  }
);

const spacetimedb = schema({
  userProfile,
  shop,
  shopInvite,
  visionQuery,
  queryResult,
});

export default spacetimedb;

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;

function sanitizeText(value: string, maxLen = 500): string {
  return (value || '').trim().slice(0, maxLen);
}

function normalizeEmail(value: string): string {
  return sanitizeText(value, 160).toLowerCase();
}

function normalizeHex(value: string): string {
  return sanitizeText(value, 128).toLowerCase().replace(/^0x/, '');
}

function generateInviteCode(ctx: Ctx, shopId: string): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let suffix = '';
  for (let i = 0; i < 6; i++) {
    const idx = ctx.random.integerInRange(0, alphabet.length - 1);
    suffix += alphabet[idx];
  }
  const prefix = shopId.slice(-4).toUpperCase();
  return `CARVIS-${prefix}-${suffix}`;
}

function extractJwtDefaults(ctx: Ctx): { name: string; email: string } {
  const jwt = ctx.senderAuth.jwt;
  if (!jwt) {
    return { name: '', email: '' };
  }
  const payload = jwt.fullPayload || {};
  const email =
    typeof payload.email === 'string'
      ? normalizeEmail(payload.email)
      : '';
  const rawName =
    typeof payload.name === 'string'
      ? payload.name
      : typeof payload.preferred_username === 'string'
        ? payload.preferred_username
        : email
          ? email.split('@')[0]
          : '';
  return {
    name: sanitizeText(rawName, 80),
    email,
  };
}

// ============================================================================
// PER-USER VIEWS (Role-Based Table Access Control)
// - Personal users have NO access to shop_calls, shop_call_results, or shop_members.
// - Mechanics (worker) have access to their shop's calls to Carvis.
// - Shop Managers (admin) see all calls made by workers in their shop + manage invites.
// ============================================================================

export const myProfile = spacetimedb.view(
  { name: 'my_profile', public: true },
  t.option(userProfile.rowType),
  ctx => ctx.db.userProfile.identity.find(ctx.sender) ?? undefined
);

export const myShop = spacetimedb.view(
  { name: 'my_shop', public: true },
  t.option(shop.rowType),
  ctx => {
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    if (!profile || profile.role === 'personal' || !profile.shopId) {
      return undefined;
    }
    return ctx.db.shop.id.find(profile.shopId) ?? undefined;
  }
);

export const shopMembers = spacetimedb.view(
  { name: 'shop_members', public: true },
  t.array(userProfile.rowType),
  ctx => {
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    if (!profile || profile.role === 'personal' || !profile.shopId) {
      return [];
    }
    return [...ctx.db.userProfile.shopId.filter(profile.shopId)];
  }
);

export const shopCalls = spacetimedb.view(
  { name: 'shop_calls', public: true },
  t.array(visionQuery.rowType),
  ctx => {
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    // Personal users do not have access to shop call tables
    if (!profile || profile.role === 'personal' || !profile.shopId) {
      return [];
    }
    // Both mechanics ('worker') and shop managers ('admin') can see calls for their shop
    return [...ctx.db.visionQuery.shopId.filter(profile.shopId)];
  }
);

export const shopCallResults = spacetimedb.view(
  { name: 'shop_call_results', public: true },
  t.array(queryResult.rowType),
  ctx => {
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    // Personal users do not have access to shop call result tables
    if (!profile || profile.role === 'personal' || !profile.shopId) {
      return [];
    }
    return [...ctx.db.queryResult.shopId.filter(profile.shopId)];
  }
);

export const visibleInvites = spacetimedb.view(
  { name: 'visible_invites', public: true },
  t.array(shopInvite.rowType),
  ctx => {
    const senderHex = ctx.sender.toHexString().toLowerCase();
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    const byId = new Map<bigint, Infer<typeof shopInvite.rowType>>();

    // Invites addressed directly to caller's SpacetimeDB Identity
    for (const inv of ctx.db.shopInvite.invitedIdentityHex.filter(senderHex)) {
      byId.set(inv.inviteId, inv);
    }

    // Invites addressed to caller's email
    if (profile && profile.email) {
      for (const inv of ctx.db.shopInvite.invitedEmail.filter(profile.email)) {
        byId.set(inv.inviteId, inv);
      }
    }

    // Shop Managers (admin) see all invites sent from their shop
    if (profile && profile.role === 'admin' && profile.shopId) {
      for (const inv of ctx.db.shopInvite.shopId.filter(profile.shopId)) {
        byId.set(inv.inviteId, inv);
      }
    }

    return [...byId.values()];
  }
);

// ============================================================================
// LIFECYCLE HOOKS
// ============================================================================

export const init = spacetimedb.init(_ctx => {});

export const onConnect = spacetimedb.clientConnected(ctx => {
  const existing = ctx.db.userProfile.identity.find(ctx.sender);
  if (existing) {
    const jwtDefaults = extractJwtDefaults(ctx);
    ctx.db.userProfile.identity.update({
      ...existing,
      email: existing.email || jwtDefaults.email,
      name: existing.name || jwtDefaults.name || existing.name,
      lastSeenAt: ctx.timestamp,
    });
  }
});

export const onDisconnect = spacetimedb.clientDisconnected(ctx => {
  const existing = ctx.db.userProfile.identity.find(ctx.sender);
  if (existing) {
    ctx.db.userProfile.identity.update({
      ...existing,
      lastSeenAt: ctx.timestamp,
    });
  }
});

// ============================================================================
// AUTH & ROLE / SHOP MANAGEMENT REDUCERS
// ============================================================================

export const registerOrUpdateProfile = spacetimedb.reducer(
  {
    name: t.string(),
    email: t.string(),
    requestedRole: t.string(), // 'admin' | 'worker' | 'personal'
    shopName: t.string(),
  },
  (ctx, { name, email, requestedRole, shopName }) => {
    const jwtDefaults = extractJwtDefaults(ctx);
    const cleanName =
      sanitizeText(name, 80) ||
      jwtDefaults.name ||
      `User-${ctx.sender.toHexString().slice(0, 6)}`;
    const cleanEmail = normalizeEmail(email) || jwtDefaults.email;
    const senderHex = ctx.sender.toHexString().toLowerCase();
    const existing = ctx.db.userProfile.identity.find(ctx.sender);

    const normalizedRole =
      requestedRole === 'admin' ||
      requestedRole === 'worker' ||
      requestedRole === 'personal'
        ? requestedRole
        : 'personal';

    let finalRole = normalizedRole;
    let finalShopId = existing?.shopId || '';

    if (normalizedRole === 'admin') {
      // Check if user already owns a shop
      const ownedShops = [...ctx.db.shop.ownerIdentity.filter(ctx.sender)];
      if (ownedShops.length > 0) {
        const owned = ownedShops[0];
        finalShopId = owned.id;
        if (sanitizeText(shopName, 100)) {
          ctx.db.shop.id.update({
            ...owned,
            name: sanitizeText(shopName, 100),
            ownerName: cleanName,
          });
        }
      } else {
        finalShopId = `shop_${senderHex.slice(0, 12)}`;
        const code = generateInviteCode(ctx, finalShopId);
        ctx.db.shop.insert({
          id: finalShopId,
          name: sanitizeText(shopName, 100) || `${cleanName}'s Auto Shop`,
          inviteCode: code,
          ownerIdentity: ctx.sender,
          ownerName: cleanName,
          createdAt: ctx.timestamp,
        });
      }
    } else if (normalizedRole === 'worker') {
      // Keep existing shop membership if already in a shop, or auto-accept pending invite
      if (!finalShopId) {
        const byHex = [
          ...ctx.db.shopInvite.invitedIdentityHex.filter(senderHex),
        ].find(i => i.status === 'pending');
        const byEmail =
          !byHex && cleanEmail
            ? [...ctx.db.shopInvite.invitedEmail.filter(cleanEmail)].find(
                i => i.status === 'pending'
              )
            : undefined;
        const pendingInvite = byHex || byEmail;
        if (pendingInvite) {
          finalShopId = pendingInvite.shopId;
          ctx.db.shopInvite.inviteId.update({
            ...pendingInvite,
            invitedIdentityHex: senderHex,
            status: 'accepted',
          });
        } else {
          throw new SenderError(
            'Mechanics must be invited by a Shop Manager or join with a Shop Invite Code.'
          );
        }
      }
    } else {
      // Personal user: strictly isolated from shop tables
      finalRole = 'personal';
      finalShopId = '';
    }

    if (existing) {
      ctx.db.userProfile.identity.update({
        ...existing,
        name: cleanName,
        email: cleanEmail,
        role: finalRole,
        shopId: finalShopId,
        lastSeenAt: ctx.timestamp,
      });
    } else {
      ctx.db.userProfile.insert({
        identity: ctx.sender,
        identityHex: senderHex,
        name: cleanName,
        email: cleanEmail,
        role: finalRole,
        shopId: finalShopId,
        createdAt: ctx.timestamp,
        lastSeenAt: ctx.timestamp,
      });
    }
  }
);

export const inviteWorker = spacetimedb.reducer(
  {
    targetIdentityOrEmail: t.string(),
  },
  (ctx, { targetIdentityOrEmail }) => {
    const adminProfile = ctx.db.userProfile.identity.find(ctx.sender);
    if (!adminProfile || adminProfile.role !== 'admin' || !adminProfile.shopId) {
      throw new SenderError('Only Shop Managers (admin role) can invite users to a shop.');
    }

    const shopRow = ctx.db.shop.id.find(adminProfile.shopId);
    if (!shopRow) {
      throw new SenderError('Shop record not found.');
    }

    const rawTarget = sanitizeText(targetIdentityOrEmail, 160);
    if (!rawTarget) {
      throw new SenderError('Provide a user SpacetimeDB Identity or email address.');
    }

    let targetHex = '';
    let targetEmail = '';

    if (rawTarget.includes('@')) {
      targetEmail = normalizeEmail(rawTarget);
      const matchedUser = [...ctx.db.userProfile.email.filter(targetEmail)][0];
      if (matchedUser) {
        targetHex = matchedUser.identityHex;
      }
    } else {
      targetHex = normalizeHex(rawTarget);
      const matchedUser = ctx.db.userProfile.identityHex.find(targetHex);
      if (matchedUser && matchedUser.email) {
        targetEmail = matchedUser.email;
      }
    }

    ctx.db.shopInvite.insert({
      inviteId: 0n,
      shopId: shopRow.id,
      shopName: shopRow.name,
      invitedByIdentity: ctx.sender,
      invitedByName: adminProfile.name,
      invitedIdentityHex: targetHex,
      invitedEmail: targetEmail,
      status: 'pending',
      createdAt: ctx.timestamp,
    });
  }
);

export const acceptInvite = spacetimedb.reducer(
  {
    inviteId: t.u64(),
  },
  (ctx, { inviteId }) => {
    const invite = ctx.db.shopInvite.inviteId.find(inviteId);
    if (!invite || invite.status !== 'pending') {
      throw new SenderError('Invite not found or no longer pending.');
    }

    const senderHex = ctx.sender.toHexString().toLowerCase();
    const profile = ctx.db.userProfile.identity.find(ctx.sender);

    const matchesHex =
      Boolean(invite.invitedIdentityHex) &&
      invite.invitedIdentityHex === senderHex;
    const matchesEmail =
      Boolean(invite.invitedEmail) &&
      Boolean(profile?.email) &&
      invite.invitedEmail === profile?.email;

    if (!matchesHex && !matchesEmail) {
      throw new SenderError('This shop invite is not addressed to your account.');
    }

    const jwtDefaults = extractJwtDefaults(ctx);
    if (profile) {
      ctx.db.userProfile.identity.update({
        ...profile,
        role: 'worker',
        shopId: invite.shopId,
        lastSeenAt: ctx.timestamp,
      });
    } else {
      ctx.db.userProfile.insert({
        identity: ctx.sender,
        identityHex: senderHex,
        name: jwtDefaults.name || `Mechanic-${senderHex.slice(0, 6)}`,
        email: jwtDefaults.email || invite.invitedEmail,
        role: 'worker',
        shopId: invite.shopId,
        createdAt: ctx.timestamp,
        lastSeenAt: ctx.timestamp,
      });
    }

    ctx.db.shopInvite.inviteId.update({
      ...invite,
      invitedIdentityHex: senderHex,
      status: 'accepted',
    });
  }
);

export const declineInvite = spacetimedb.reducer(
  {
    inviteId: t.u64(),
  },
  (ctx, { inviteId }) => {
    const invite = ctx.db.shopInvite.inviteId.find(inviteId);
    if (!invite || invite.status !== 'pending') {
      throw new SenderError('Invite not found or no longer pending.');
    }
    const senderHex = ctx.sender.toHexString().toLowerCase();
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    const matchesHex =
      Boolean(invite.invitedIdentityHex) &&
      invite.invitedIdentityHex === senderHex;
    const matchesEmail =
      Boolean(invite.invitedEmail) &&
      Boolean(profile?.email) &&
      invite.invitedEmail === profile?.email;

    if (!matchesHex && !matchesEmail) {
      throw new SenderError('Unauthorized to decline this invite.');
    }

    ctx.db.shopInvite.inviteId.update({
      ...invite,
      status: 'declined',
    });
  }
);

export const joinShopByCode = spacetimedb.reducer(
  {
    inviteCode: t.string(),
  },
  (ctx, { inviteCode }) => {
    const cleanCode = sanitizeText(inviteCode, 40).toUpperCase();
    const shopRow = ctx.db.shop.inviteCode.find(cleanCode);
    if (!shopRow) {
      throw new SenderError('Invalid shop invite code.');
    }

    const senderHex = ctx.sender.toHexString().toLowerCase();
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    const jwtDefaults = extractJwtDefaults(ctx);

    if (profile) {
      ctx.db.userProfile.identity.update({
        ...profile,
        role: profile.identity.equals(shopRow.ownerIdentity) ? 'admin' : 'worker',
        shopId: shopRow.id,
        lastSeenAt: ctx.timestamp,
      });
    } else {
      ctx.db.userProfile.insert({
        identity: ctx.sender,
        identityHex: senderHex,
        name: jwtDefaults.name || `Mechanic-${senderHex.slice(0, 6)}`,
        email: jwtDefaults.email,
        role: ctx.sender.equals(shopRow.ownerIdentity) ? 'admin' : 'worker',
        shopId: shopRow.id,
        createdAt: ctx.timestamp,
        lastSeenAt: ctx.timestamp,
      });
    }
  }
);

export const revokeInvite = spacetimedb.reducer(
  {
    inviteId: t.u64(),
  },
  (ctx, { inviteId }) => {
    const adminProfile = ctx.db.userProfile.identity.find(ctx.sender);
    const invite = ctx.db.shopInvite.inviteId.find(inviteId);
    if (
      !adminProfile ||
      adminProfile.role !== 'admin' ||
      !invite ||
      invite.shopId !== adminProfile.shopId
    ) {
      throw new SenderError('Only the Shop Manager can revoke this invite.');
    }
    ctx.db.shopInvite.inviteId.update({
      ...invite,
      status: 'revoked',
    });
  }
);

export const removeShopWorker = spacetimedb.reducer(
  {
    workerIdentityHex: t.string(),
  },
  (ctx, { workerIdentityHex }) => {
    const adminProfile = ctx.db.userProfile.identity.find(ctx.sender);
    if (!adminProfile || adminProfile.role !== 'admin' || !adminProfile.shopId) {
      throw new SenderError('Only Shop Managers can remove workers.');
    }
    const cleanHex = normalizeHex(workerIdentityHex);
    const worker = ctx.db.userProfile.identityHex.find(cleanHex);
    if (!worker || worker.shopId !== adminProfile.shopId) {
      throw new SenderError('Worker not found in your shop.');
    }
    if (worker.identity.equals(ctx.sender)) {
      throw new SenderError('Shop Managers cannot remove themselves.');
    }
    ctx.db.userProfile.identity.update({
      ...worker,
      role: 'personal',
      shopId: '',
    });
  }
);

// ============================================================================
// CARVIS SHOP CALL LOGGING REDUCERS
// Strictly restricted to Shop Mechanics ('worker') and Shop Managers ('admin').
// Personal users ('personal') are blocked from writing to shop tables.
// ============================================================================

export const startShopQuery = spacetimedb.reducer(
  {
    queryId: t.string(),
    sessionId: t.string(),
    vehicleYear: t.string(),
    vehicleMake: t.string(),
    vehicleModel: t.string(),
    question: t.string(),
  },
  (ctx, { queryId, sessionId, vehicleYear, vehicleMake, vehicleModel, question }) => {
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    if (!profile || profile.role === 'personal' || !profile.shopId) {
      throw new SenderError('Personal users do not have access to shop call tables.');
    }

    const cleanId = sanitizeText(queryId, 64);
    if (!cleanId) {
      throw new SenderError('queryId is required.');
    }

    const existing = ctx.db.visionQuery.id.find(cleanId);
    const row = {
      id: cleanId,
      sessionId: sanitizeText(sessionId, 64),
      shopId: profile.shopId,
      callerIdentity: ctx.sender,
      callerName: profile.name,
      callerRole: profile.role,
      vehicleYear: sanitizeText(vehicleYear, 16),
      vehicleMake: sanitizeText(vehicleMake, 64),
      vehicleModel: sanitizeText(vehicleModel, 64),
      question: sanitizeText(question, 500),
      component: existing?.component || '',
      confidence: existing?.confidence || 0,
      status: 'identifying',
      createdAt: existing?.createdAt || ctx.timestamp,
      updatedAt: ctx.timestamp,
    };

    if (existing) {
      ctx.db.visionQuery.id.update(row);
    } else {
      ctx.db.visionQuery.insert(row);
    }
  }
);

export const recordShopQueryResult = spacetimedb.reducer(
  {
    queryId: t.string(),
    component: t.string(),
    confidence: t.f64(),
    status: t.string(), // 'answered' | 'refused' | 'failed'
    answer: t.string(),
    sourceRef: t.string(),
    sourceGrounded: t.bool(),
    latencyMs: t.u32(),
  },
  (
    ctx,
    {
      queryId,
      component,
      confidence,
      status,
      answer,
      sourceRef,
      sourceGrounded,
      latencyMs,
    }
  ) => {
    const profile = ctx.db.userProfile.identity.find(ctx.sender);
    if (!profile || profile.role === 'personal' || !profile.shopId) {
      throw new SenderError('Personal users do not have access to shop call tables.');
    }

    const cleanId = sanitizeText(queryId, 64);
    const existingQuery = ctx.db.visionQuery.id.find(cleanId);
    if (!existingQuery || existingQuery.shopId !== profile.shopId) {
      throw new SenderError('Matching shop query not found.');
    }

    const safeStatus =
      status === 'answered' || status === 'refused' || status === 'failed'
        ? status
        : 'failed';

    ctx.db.visionQuery.id.update({
      ...existingQuery,
      component: sanitizeText(component, 120),
      confidence,
      status: safeStatus,
      updatedAt: ctx.timestamp,
    });

    const existingResult = ctx.db.queryResult.queryId.find(cleanId);
    const resultRow = {
      queryId: cleanId,
      shopId: profile.shopId,
      callerIdentity: ctx.sender,
      callerName: profile.name,
      answer: sanitizeText(answer, 1200),
      sourceRef: sanitizeText(sourceRef, 200),
      sourceGrounded,
      latencyMs,
      createdAt: ctx.timestamp,
    };

    if (existingResult) {
      ctx.db.queryResult.queryId.update(resultRow);
    } else {
      ctx.db.queryResult.insert(resultRow);
    }
  }
);
