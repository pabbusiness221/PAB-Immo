// ============================================================
// traduire-description — Supabase Edge Function
// Traduit la description française d'un bien en anglais, à la demande du
// premier visiteur anglophone qui la consulte, puis met le résultat en cache
// dans properties.description_en pour tous les visiteurs suivants.
// ============================================================
//
// PUBLIQUE, PAS ADMIN
// Comme parser-recherche : sert les visiteurs du site, pas l'administration.
// Aucune vérification d'identité — seule la clé Groq reste côté serveur.
//
// POURQUOI CETTE FONCTION ET PAS UN SIMPLE db.from('properties').update()
// CÔTÉ CLIENT
// Écrire depuis le navigateur demanderait d'ouvrir une policy RLS
// d'UPDATE public sur `properties`, une table par ailleurs réservée au
// propriétaire — même en la limitant en apparence à une seule colonne, RLS
// raisonne par ligne, pas par colonne : n'importe quel visiteur pourrait
// alors réécrire n'importe quel champ. Ici, la fonction lit et écrit avec la
// clé de service, et ne renvoie jamais que le texte traduit.
//
// SÉCURITÉ : seuls les biens PUBLIÉS et non archivés peuvent être traduits —
// jamais un identifiant arbitraire, qui exposerait autrement la description
// d'un bien retiré de la vitrine.
//
// PLAFOND D'APPELS (ajouté le 9 août 2026, point M1 de l'audit)
// La fonction étant publique, rien n'empêchait d'enchaîner les appels pour
// épuiser le quota Groq gratuit et priver les visiteurs de traduction. Le
// compteur (consommer_quota_ia, table submission_log) n'est consulté que sur
// le chemin payant, jamais pour servir une traduction déjà en cache.
//
// Secrets requis : GROQ_API_KEY (même secret que generer-description),
// SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
const GROQ_API_KEY = Deno.env.get("GROQ_API_KEY");
const GROQ_MODEL = Deno.env.get("GROQ_MODEL") || "llama-3.3-70b-versatile";

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

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reponse({ erreur: "Méthode non autorisée." }, 405);

  if (!SUPABASE_URL || !SERVICE_KEY) {
    return reponse({ erreur: "Fonction mal configurée." }, 500);
  }
  if (!GROQ_API_KEY) {
    return reponse({ erreur: "Traduction indisponible : clé IA non configurée côté serveur." }, 500);
  }

  let corps: Record<string, any> = {};
  try {
    corps = await req.json();
  } catch {
    return reponse({ erreur: "Requête invalide." }, 400);
  }

  const ref = String(corps.ref || "").trim();
  if (!ref) return reponse({ erreur: "Référence de bien manquante." }, 400);

  const proprieteRes = await fetch(
    `${SUPABASE_URL}/rest/v1/properties?ref=eq.${encodeURIComponent(ref)}&is_published=eq.true&archived_at=is.null&select=id,description,description_en`,
    { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
  );
  if (!proprieteRes.ok) {
    return reponse({ erreur: "Bien introuvable." }, 404);
  }
  const lignes = await proprieteRes.json();
  const bien = lignes?.[0];
  if (!bien) return reponse({ erreur: "Bien introuvable." }, 404);

  // Déjà traduite : aucun appel Groq, on renvoie le cache tel quel.
  if (bien.description_en) {
    return reponse({ description_en: bien.description_en });
  }
  if (!bien.description || !bien.description.trim()) {
    return reponse({ description_en: "" });
  }

  // Plafond — placé APRÈS le cache, délibérément : une traduction déjà en base
  // ne coûte rien et ne doit jamais être refusée. Seul le chemin payant (appel
  // Groq) est compté, si bien qu'un visiteur qui parcourt tout le catalogue
  // déjà traduit n'est jamais bloqué.
  //
  // cf-connecting-ip / sb-forwarded-for sont posés par l'infrastructure ;
  // x-forwarded-for est fourni par le client et serait donc contournable en le
  // faisant varier (même raisonnement que enforce_submission_rate_limit).
  const ip = req.headers.get("cf-connecting-ip") ||
             req.headers.get("sb-forwarded-for") ||
             "inconnu";

  const quotaRes = await fetch(`${SUPABASE_URL}/rest/v1/rpc/consommer_quota_ia`, {
    method: "POST",
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ p_bucket: "traduction", p_ip: ip }),
  });

  // Un incident sur le compteur ne doit pas priver les visiteurs de traduction,
  // mais il ne doit pas non plus ouvrir le robinet en grand : on refuse, et le
  // message reste réessayable.
  if (!quotaRes.ok) {
    console.error("Quota injoignable:", quotaRes.status, await quotaRes.text().catch(() => ""));
    return reponse({ erreur: "Traduction momentanément indisponible. Réessayez." }, 503);
  }
  if (await quotaRes.json().catch(() => false) !== true) {
    return reponse({ erreur: "Trop de traductions demandées récemment. Réessayez dans une heure." }, 429);
  }

  const prompt = `Translate the following French real estate listing description into natural, professional English. Do not add, omit, or invent any information — a faithful translation only. Respond with ONLY the translated text, no quotes, no title.\n\n${bien.description}`;

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
        temperature: 0.2,
        max_tokens: 500,
      }),
    });
  } catch (err) {
    console.error("Appel Groq impossible:", err);
    return reponse({ erreur: "Le service de traduction est injoignable. Réessayez." }, 502);
  }

  if (!groqRes.ok) {
    const errText = await groqRes.text().catch(() => "");
    console.error("Échec Groq:", groqRes.status, errText);
    if (groqRes.status === 429) {
      return reponse({ erreur: "Quota gratuit atteint pour l'instant. Réessayez dans quelques minutes." }, 502);
    }
    return reponse({ erreur: "La traduction a échoué." }, 502);
  }

  const result = await groqRes.json().catch(() => null);
  const traduction: string = (result?.choices?.[0]?.message?.content ?? "").trim();
  if (!traduction) {
    return reponse({ erreur: "La traduction n'a produit aucun texte. Réessayez." }, 502);
  }

  // Mise en cache — best effort : un échec d'écriture ne doit pas priver CE
  // visiteur de la traduction qu'il vient d'obtenir, seulement empêcher
  // qu'elle profite aux suivants.
  const majRes = await fetch(`${SUPABASE_URL}/rest/v1/properties?id=eq.${bien.id}`, {
    method: "PATCH",
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({ description_en: traduction }),
  });
  if (!majRes.ok) {
    console.error("Échec de la mise en cache de la traduction:", await majRes.text().catch(() => ""));
  }

  return reponse({ description_en: traduction });
});
