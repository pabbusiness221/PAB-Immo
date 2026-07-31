// ============================================================
// inviter-agence — Supabase Edge Function
// Ouvre un compte pour une agence partenaire, depuis l'espace
// d'administration, et lui envoie un lien d'invitation par email.
// ============================================================
//
// POURQUOI UNE FONCTION SERVEUR
// Créer un compte utilisateur exige la clé de service Supabase, qui donne un
// accès TOTAL à la base. Cette clé ne peut jamais figurer dans le code d'une
// page web : le dépôt est public, et le code d'un site est de toute façon
// lisible par tout visiteur. Elle ne vit donc que dans les secrets de cette
// fonction, exécutée sur les serveurs de Supabase.
//
// L'admin appelle cette fonction avec SON jeton de session. La fonction
// vérifie elle-même que ce jeton appartient bien à l'administrateur avant
// d'agir — on ne fait jamais confiance à ce que la page déclare.
//
// Secrets requis : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ADMIN_USER_ID
//                  SITE_REDIRECT_URL (adresse où l'agence choisit son mot de passe)

const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
// L'identifiant de l'admin est un secret de configuration, pas une valeur
// écrite en dur : le jour où il change, on le change ici sans redéployer.
const ADMIN_USER_ID = Deno.env.get("ADMIN_USER_ID");
const REDIRECT_URL = Deno.env.get("SITE_REDIRECT_URL") || "";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function reponse(corps: unknown, statut = 200) {
  return new Response(JSON.stringify(corps), {
    status: statut,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

// Vérifie que l'appelant est bien l'administrateur, à partir de son jeton.
// Retourne son identifiant, ou null si le jeton est absent, invalide, expiré,
// ou appartient à quelqu'un d'autre.
async function identifierAdmin(req: Request): Promise<string | null> {
  const entete = req.headers.get("Authorization") || "";
  const jeton = entete.startsWith("Bearer ") ? entete.slice(7) : "";
  if (!jeton) return null;

  // On demande à Supabase À QUI appartient ce jeton. C'est Supabase qui
  // valide la signature et l'expiration — jamais nous.
  const res = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { apikey: SERVICE_KEY!, Authorization: `Bearer ${jeton}` },
  });
  if (!res.ok) return null;
  const utilisateur = await res.json();
  const id = utilisateur?.id;
  if (!id || id !== ADMIN_USER_ID) return null;
  return id;
}

function emailValide(email: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reponse({ erreur: "Méthode non autorisée." }, 405);

  if (!SUPABASE_URL || !SERVICE_KEY || !ADMIN_USER_ID) {
    return reponse({ erreur: "Fonction mal configurée : secrets manquants." }, 500);
  }

  const adminId = await identifierAdmin(req);
  if (!adminId) {
    // Message volontairement avare : on ne dit pas si le jeton est invalide ou
    // simplement non-admin. Rien à apprendre pour qui tâtonne.
    return reponse({ erreur: "Action réservée à l'administrateur." }, 403);
  }

  let corps: Record<string, string> = {};
  try { corps = await req.json(); } catch { /* corps vide traité plus bas */ }

  const email = String(corps.email || "").trim().toLowerCase();
  const nom = String(corps.display_name || "").trim();
  const contact = String(corps.contact_name || "").trim();
  const telephone = String(corps.phone || "").trim();
  const zone = String(corps.zone || "").trim();

  if (!emailValide(email)) return reponse({ erreur: "Adresse email invalide." }, 400);
  if (!nom) return reponse({ erreur: "Le nom de l'agence est obligatoire." }, 400);

  // --- 1. Inviter : Supabase crée le compte et envoie le lien d'activation ---
  // L'agence choisit elle-même son mot de passe. Personne, pas même l'admin,
  // ne le connaît — c'est tout l'intérêt de l'invitation face à un mot de
  // passe temporaire transmis de la main à la main.
  const invitation = await fetch(`${SUPABASE_URL}/auth/v1/invite`, {
    method: "POST",
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email,
      data: { display_name: nom },
      ...(REDIRECT_URL ? { redirect_to: REDIRECT_URL } : {}),
    }),
  });

  const invite = await invitation.json().catch(() => ({}));

  if (!invitation.ok) {
    const message = String(invite?.msg || invite?.message || "");
    // Cas courant et sans gravité : l'adresse a déjà un compte. On le dit
    // clairement plutôt que de renvoyer une erreur technique brute.
    if (/already|registered|exists|duplicate/i.test(message)) {
      return reponse({ erreur: "Cette adresse a déjà un compte. Utilisez-en une autre, ou rattachez le compte existant depuis Supabase." }, 409);
    }
    return reponse({ erreur: "L'invitation n'a pas pu être envoyée : " + (message || "erreur inconnue") }, 502);
  }

  const userId = invite?.id || invite?.user?.id;
  if (!userId) {
    return reponse({ erreur: "Compte créé, mais son identifiant est introuvable. Vérifiez dans Supabase." }, 502);
  }

  // --- 2. Créer la fiche agence ---------------------------------------------
  // Le compte existe déjà à ce stade : si cette écriture échoue, on le dit
  // franchement plutôt que de laisser un compte orphelin sans explication.
  const fiche = await fetch(`${SUPABASE_URL}/rest/v1/collaborators`, {
    method: "POST",
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify({
      user_id: userId,
      display_name: nom,
      contact_name: contact || null,
      phone: telephone || null,
      email,
      zone: zone || null,
      invited_at: new Date().toISOString(),
      invited_by: adminId,
    }),
  });

  if (!fiche.ok) {
    const detail = await fiche.text().catch(() => "");
    return reponse({
      erreur: "Le compte a bien été créé et l'invitation envoyée, mais la fiche agence n'a pas pu être enregistrée. Détail : " + detail,
      user_id: userId,
    }, 502);
  }

  return reponse({
    ok: true,
    user_id: userId,
    message: `Invitation envoyée à ${email}. L'agence choisira son mot de passe depuis le lien reçu.`,
  });
});
