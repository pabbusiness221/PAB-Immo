// ============================================================
// notify-alert-matches — Supabase Edge Function
// Déclenchée par un trigger SQL sur public.properties quand un bien
// devient nouvellement visible (publié + Disponible/Réservé).
// Cherche les inscriptions aux alertes dont les critères correspondent,
// et envoie un email à chaque inscrit correspondant via Resend.
// ============================================================
//
// Sauvegarde du code déployé (version 7, récupérée le 21/07/2026).
// Secrets requis : RESEND_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
//                  ALERT_LISTING_URL, NOTIFY_FROM (optionnel)

const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");
const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
// URL de base de la vitrine, utilisée pour le lien dans l'email.
// Modifiable via un secret ALERT_LISTING_URL sans avoir à redéployer le code.
const LISTING_URL = Deno.env.get("ALERT_LISTING_URL") || "";

const fcfa = (n: number) => Number(n).toLocaleString("fr-FR") + " FCFA";

function escapeHtml(str: string) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Cherche les inscriptions actives dont les critères (type, opération,
// région, budget max) correspondent au bien reçu. Un critère vide côté
// inscrit ("Tous types" par ex.) est toujours considéré comme un match.
async function findMatchingSubscriptions(property: Record<string, any>) {
  const enc = (v: string) => encodeURIComponent(v);
  const filter =
    `and=(is_active.eq.true,` +
    `or(type.is.null,type.eq.${enc(property.type)}),` +
    `or(operation.is.null,operation.eq.${enc(property.operation)}),` +
    `or(region.is.null,region.eq.${enc(property.region)}),` +
    `or(budget_max.is.null,budget_max.gte.${Number(property.price)})` +
    `)`;

  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/alert_subscriptions?${filter}&select=id,email`,
    {
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY!,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      },
    }
  );
  if (!res.ok) {
    console.error("Échec requête alert_subscriptions:", await res.text());
    return [];
  }
  return await res.json();
}

function buildEmailHtml(property: Record<string, any>) {
  // Lien direct vers la vitrine, et non vers share-preview : Supabase renvoie
  // les réponses de ses fonctions Edge en text/plain avec nosniff, si bien que
  // l'inscrit recevait le code source en texte brut au lieu de la page du bien.
  const link = LISTING_URL
    ? `${LISTING_URL}?bien=${encodeURIComponent(property.ref)}`
    : null;
  return `
    <div style="font-family:sans-serif;color:#161B22;max-width:480px;">
      <h2 style="margin:0 0 4px;">Un bien correspond à vos critères</h2>
      <p style="margin:0 0 14px;color:#5C6470;font-size:13px;">
        ${escapeHtml(property.type)} — ${property.operation}
      </p>
      <div style="background:#F1EFE7;border-radius:12px;padding:16px;margin-bottom:16px;">
        <p style="margin:0 0 6px;font-weight:700;">${escapeHtml(property.ref)}</p>
        <p style="margin:0 0 4px;color:#5C6470;font-size:13px;">
          ${escapeHtml(property.commune)}, ${escapeHtml(property.region)}
        </p>
        <p style="margin:0 0 4px;font-size:13px;">${property.surface} ${property.type === "Champ agricole" ? "ha" : "m²"}</p>
        <p style="margin:8px 0 0;font-weight:700;color:#B8842A;">
          ${fcfa(property.price)}${property.operation === "Location" ? " /mois" : ""}
        </p>
      </div>
      ${link ? `<p style="margin:0 0 16px;"><a href="${link}" style="background:#1B4F91;color:#fff;padding:10px 18px;border-radius:999px;text-decoration:none;font-weight:700;font-size:13px;">Voir ce bien</a></p>` : ""}
      <p style="margin:16px 0 0;color:#8B9199;font-size:11.5px;">
        Vous recevez cet email car vous vous êtes inscrit(e) aux alertes PAB Immo.
        Pour ne plus les recevoir, répondez à cet email ou contactez-nous.
      </p>
    </div>
  `;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }
  if (!RESEND_API_KEY || !SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) {
    console.error("Secrets manquants (RESEND_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).");
    return new Response("Missing configuration", { status: 500 });
  }

  let property: Record<string, any>;
  try {
    property = await req.json();
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  if (!property?.ref || !property?.type) {
    return new Response("Invalid property payload", { status: 400 });
  }

  const subscriptions = await findMatchingSubscriptions(property);

  if (subscriptions.length === 0) {
    return new Response("No matching subscriptions", { status: 200 });
  }

  const html = buildEmailHtml(property);
  const subject = `🏡 Nouveau bien correspondant à vos critères — ${property.ref}`;
  const from = Deno.env.get("NOTIFY_FROM") || "PAB Immo <onboarding@resend.dev>";

  let sent = 0;
  let failed = 0;

  for (const sub of subscriptions) {
    try {
      const res = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${RESEND_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          from,
          to: [sub.email],
          subject,
          html,
        }),
      });
      if (res.ok) sent++;
      else {
        failed++;
        console.error(`Échec envoi à ${sub.email}:`, await res.text());
      }
    } catch (err) {
      failed++;
      console.error(`Erreur réseau pour ${sub.email}:`, err);
    }
  }

  return new Response(JSON.stringify({ matched: subscriptions.length, sent, failed }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
