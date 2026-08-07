// ============================================================
// generer-description — Supabase Edge Function
// Rédige une proposition de description d'annonce à partir des champs
// structurés du formulaire (type, lieu, surface, prix, pièces, statut
// foncier, équipements) — jamais des photos, pour ne jamais risquer
// d'inventer ce qu'une image montre ou non.
// ============================================================
//
// POURQUOI GROQ ET NON GEMINI
// Gemini a d'abord été essayé : son niveau gratuit s'est révélé indisponible
// pour ce compte (quota 0, très probablement une restriction géographique de
// Google — le niveau 100% gratuit sans carte n'est ouvert que dans une liste
// de pays qui ne couvre pas forcément tous les pays). Groq utilise un
// mécanisme de quota différent, non lié à une éligibilité de facturation par
// pays, et propose un niveau gratuit permanent sans carte bancaire.
//
// POURQUOI UNE FONCTION SERVEUR
// La clé de l'API IA ne peut jamais figurer dans le code de
// Portefeuille-Immo.html : le dépôt est public, et le code d'une page web est
// de toute façon lisible par n'importe quel visiteur qui ouvre les outils de
// développement. Elle ne vit donc que dans les secrets de cette fonction.
//
// L'admin appelle cette fonction avec SON jeton de session (via
// db.functions.invoke, qui l'ajoute automatiquement). La fonction vérifie
// elle-même que ce jeton appartient bien à l'administrateur avant d'agir —
// même vérification que inviter-agence, via is_admin() en base.
//
// Secrets requis :
//   GROQ_API_KEY  — à créer sur console.groq.com (gratuit, sans carte —
//                   compte email ou Google), puis à ajouter dans Supabase →
//                   Edge Functions → Secrets. Rien d'autre à configurer pour
//                   changer de clé.
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY — fournis d'office par Supabase.
// Optionnel :
//   GROQ_MODEL — nom du modèle Groq, par défaut "llama-3.3-70b-versatile".
//                À modifier ici seulement si Groq en propose un plus récent
//                ou retire celui-ci, sans toucher au reste du code.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
const GROQ_API_KEY = Deno.env.get("GROQ_API_KEY");
const GROQ_MODEL = Deno.env.get("GROQ_MODEL") || "llama-3.3-70b-versatile";

// supabase-js (db.functions.invoke) ajoute de lui-même apikey et x-client-info
// à chaque appel, en plus d'authorization et content-type. Un seul en-tête
// manquant ici fait échouer le préflight CORS silencieusement — le navigateur
// n'envoie même pas la vraie requête, et l'erreur reçue côté client
// (« Failed to send a request to the Edge Function ») ne dit pas pourquoi.
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function reponse(corps: unknown, statut = 200) {
  return new Response(JSON.stringify(corps), {
    status: statut,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

// Même vérification que inviter-agence : le jeton doit appartenir à
// l'administrateur, tranché en base par is_admin() plutôt que par une
// comparaison recopiée ici (une seule source de vérité pour « qui est admin »).
async function identifierAdmin(req: Request): Promise<string | null> {
  const entete = req.headers.get("Authorization") || "";
  const jeton = entete.startsWith("Bearer ") ? entete.slice(7) : "";
  if (!jeton) return null;

  const res = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { apikey: SERVICE_KEY!, Authorization: `Bearer ${jeton}` },
  });
  if (!res.ok) return null;
  const id = (await res.json())?.id;
  if (!id) return null;

  const verdict = await fetch(`${SUPABASE_URL}/rest/v1/rpc/is_admin`, {
    method: "POST",
    headers: {
      apikey: SERVICE_KEY!,
      Authorization: `Bearer ${jeton}`,
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  if (!verdict.ok) return null;
  return (await verdict.json()) === true ? id : null;
}

// Une seule liste de faits, construite uniquement à partir de ce que l'admin
// a réellement saisi — jamais de valeur par défaut inventée pour un champ vide.
function listerFaits(c: Record<string, any>): string[] {
  const faits: string[] = [];
  if (c.type) faits.push(`Type de bien : ${c.type}`);
  if (c.operation) faits.push(`Opération : ${c.operation === "Location" ? "à louer" : "à vendre"}`);
  const lieu = [c.quartier, c.commune, c.region].filter(Boolean).join(", ");
  if (lieu) faits.push(`Localisation : ${lieu}`);
  if (c.surface) faits.push(`Superficie : ${c.surface} m²`);
  if (c.price) {
    const prix = Number(c.price).toLocaleString("fr-FR");
    faits.push(`Prix : ${prix} FCFA${c.operation === "Location" ? " par mois" : ""}`);
  }
  if (c.chambres) faits.push(`Chambres : ${c.chambres}`);
  if (c.salons) faits.push(`Salons : ${c.salons}`);
  if (c.salles_bain) faits.push(`Salles de bain : ${c.salles_bain}`);
  if (c.cuisine) faits.push(`Cuisine : ${c.cuisine}`);
  if (c.statut_foncier && c.statut_foncier !== "Non renseigné") {
    faits.push(`Statut foncier : ${c.statut_foncier}`);
  }
  if (Array.isArray(c.equipements) && c.equipements.length) {
    faits.push(`Équipements : ${c.equipements.join(", ")}`);
  }
  return faits;
}

function construirePrompt(faits: string[]): string {
  return `Tu rédiges une description d'annonce immobilière en français, pour une agence sénégalaise (PAB Immo, région de Dakar et Thiès).

Voici UNIQUEMENT les faits vérifiés sur ce bien :
${faits.map((f) => "- " + f).join("\n")}

Consignes strictes :
- N'utilise QUE les faits ci-dessus. N'invente aucune caractéristique absente de cette liste (pas de « vue dégagée », « récemment rénové », « quartier calme », etc. si ce n'est pas mentionné).
- Ton professionnel, clair et honnête — pas de superlatifs vides, pas d'emoji.
- Environ 80 à 120 mots, un ou deux courts paragraphes.
- Termine par une phrase brève invitant à contacter l'agence pour plus de détails ou une visite.
- Réponds uniquement avec le texte de la description, sans titre ni guillemets.`;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reponse({ erreur: "Méthode non autorisée." }, 405);

  if (!SUPABASE_URL || !SERVICE_KEY) {
    return reponse({ erreur: "Fonction mal configurée." }, 500);
  }
  if (!GROQ_API_KEY) {
    return reponse({ erreur: "Génération indisponible : clé IA non configurée côté serveur." }, 500);
  }

  const adminId = await identifierAdmin(req);
  if (!adminId) {
    return reponse({ erreur: "Action réservée à l'administrateur." }, 403);
  }

  let champs: Record<string, any> = {};
  try {
    champs = await req.json();
  } catch {
    return reponse({ erreur: "Requête invalide." }, 400);
  }

  if (!champs.commune || !champs.surface || !champs.price) {
    return reponse({ erreur: "Commune, superficie et prix sont nécessaires pour générer une description." }, 400);
  }

  const prompt = construirePrompt(listerFaits(champs));

  let groqRes: Response;
  try {
    groqRes = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${GROQ_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: GROQ_MODEL,
        messages: [{ role: "user", content: prompt }],
        temperature: 0.6,
        max_tokens: 350,
      }),
    });
  } catch (err) {
    console.error("Appel Groq impossible:", err);
    return reponse({ erreur: "Le service de génération est injoignable. Réessayez." }, 502);
  }

  if (!groqRes.ok) {
    const errText = await groqRes.text().catch(() => "");
    console.error("Échec Groq:", groqRes.status, errText);
    if (groqRes.status === 429) {
      return reponse({ erreur: "Quota gratuit Groq atteint pour l'instant. Réessayez dans quelques minutes." }, 502);
    }
    return reponse({ erreur: "La génération a échoué (service IA indisponible)." }, 502);
  }

  const result = await groqRes.json().catch(() => null);
  const texte: string = result?.choices?.[0]?.message?.content ?? "";
  if (!texte.trim()) {
    return reponse({ erreur: "La génération n'a produit aucun texte. Réessayez." }, 502);
  }

  return reponse({ description: texte.trim() });
});
