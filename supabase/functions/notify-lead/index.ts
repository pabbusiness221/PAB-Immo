// ============================================================
// notify-lead — Supabase Edge Function
// Envoie un email de notification via Resend, sur deux familles d'événements :
//   INSERT    — contact_messages · appointments · alert_subscriptions
//               (un prospect s'est manifesté sur la vitrine)
//   A_VALIDER — properties
//               (un collaborateur demande la mise en ligne d'un bien ; voir
//                le déclencheur notifier_bien_a_valider)
// ============================================================
//
// Sauvegarde du code déployé.
// Secrets requis : RESEND_API_KEY, NOTIFY_EMAIL, NOTIFY_FROM (optionnel),
//                  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");
const NOTIFY_EMAIL = Deno.env.get("NOTIFY_EMAIL");
const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

const fcfa = (n: number | null) =>
  n == null ? null : Number(n).toLocaleString("fr-FR") + " FCFA";

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

// Va chercher les infos du bien concerné (ref, type, commune) si property_id existe.
async function fetchProperty(propertyId: string | null) {
  if (!propertyId || !SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) return null;
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/properties?id=eq.${propertyId}&select=ref,type,commune,region`,
      {
        headers: {
          apikey: SUPABASE_SERVICE_ROLE_KEY,
          Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        },
      }
    );
    if (!res.ok) return null;
    const rows = await res.json();
    return rows?.[0] ?? null;
  } catch {
    return null;
  }
}

// Le nom lisible de l'auteur d'une demande de publication. Le déclencheur
// n'envoie que owner_id : mettre le nom dans la charge utile obligerait la base
// à joindre une table de plus à chaque soumission, alors que l'email est le seul
// endroit qui en a besoin.
async function fetchCollaborateur(ownerId: string | null) {
  if (!ownerId || !SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) return null;
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/collaborators?user_id=eq.${ownerId}&select=display_name,contact_name,email,phone`,
      {
        headers: {
          apikey: SUPABASE_SERVICE_ROLE_KEY,
          Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        },
      }
    );
    if (!res.ok) return null;
    const rows = await res.json();
    return rows?.[0] ?? null;
  } catch {
    return null;
  }
}

function escapeHtml(str: string) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Consigne l'issue de chaque envoi. Sans cette trace, une panne d'email est
// invisible : le prospect est bien enregistré, mais personne ne reçoit rien et
// personne ne le sait. L'écriture ne doit jamais faire échouer la fonction —
// mieux vaut un email envoyé sans trace qu'une trace qui bloque l'envoi.
async function journaliser(
  evenement: string,
  statut: "envoye" | "echec",
  destinataires: number,
  detail?: string,
) {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) return;
  try {
    await fetch(`${SUPABASE_URL}/rest/v1/notification_log`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify({
        source: "notify-lead",
        evenement,
        statut,
        destinataires,
        detail: detail ? String(detail).slice(0, 500) : null,
      }),
    });
  } catch (err) {
    console.error("Journalisation impossible:", err);
  }
}

async function buildEmail(table: string, record: Record<string, any>) {
  const property =
    table === "contact_messages" || table === "appointments"
      ? await fetchProperty(record.property_id)
      : null;

  const propLine = property
    ? `<p style="margin:0 0 12px;color:#5C6470;font-size:13px;">
         Bien concerné : <strong>${escapeHtml(property.ref)}</strong> —
         ${escapeHtml(property.type)}, ${escapeHtml(property.commune)}${property.region ? ", " + escapeHtml(property.region) : ""}
       </p>`
    : table !== "alert_subscriptions"
    ? `<p style="margin:0 0 12px;color:#5C6470;font-size:13px;">Bien concerné : non précisé</p>`
    : "";

  if (table === "contact_messages") {
    return {
      subject: `💬 Nouveau message — ${record.name}`,
      html: `
        <h2 style="margin:0 0 4px;">Nouveau message de contact</h2>
        ${propLine}
        <p style="margin:0 0 4px;"><strong>Nom :</strong> ${escapeHtml(record.name)}</p>
        <p style="margin:0 0 4px;"><strong>Contact :</strong> ${escapeHtml(record.contact)}</p>
        <p style="margin:12px 0;padding:12px;background:#F1EFE7;border-radius:10px;">${escapeHtml(record.message)}</p>
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Reçu le ${fmtDate(record.created_at)}</p>
      `,
    };
  }

  if (table === "appointments") {
    return {
      subject: `📅 Nouvelle demande de RDV — ${record.name}`,
      html: `
        <h2 style="margin:0 0 4px;">Nouvelle demande de rendez-vous</h2>
        ${propLine}
        <p style="margin:0 0 4px;"><strong>Nom :</strong> ${escapeHtml(record.name)}</p>
        <p style="margin:0 0 4px;"><strong>Contact :</strong> ${escapeHtml(record.contact)}</p>
        <p style="margin:0 0 4px;"><strong>Date souhaitée :</strong> ${new Date(record.preferred_date).toLocaleDateString("fr-FR")}${record.preferred_time ? " — " + escapeHtml(record.preferred_time) : ""}</p>
        ${record.message ? `<p style="margin:12px 0;padding:12px;background:#F1EFE7;border-radius:10px;">${escapeHtml(record.message)}</p>` : ""}
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Reçu le ${fmtDate(record.created_at)}</p>
      `,
    };
  }

  if (table === "alert_subscriptions") {
    const criteria = [record.type, record.operation, record.region].filter(Boolean).join(" · ") || "Tous types";
    const budget = fcfa(record.budget_max);
    return {
      subject: `🔔 Nouvelle inscription aux alertes — ${record.email}`,
      html: `
        <h2 style="margin:0 0 4px;">Nouvelle inscription aux alertes</h2>
        <p style="margin:0 0 4px;"><strong>Email :</strong> ${escapeHtml(record.email)}</p>
        <p style="margin:0 0 4px;"><strong>Critères :</strong> ${escapeHtml(criteria)}</p>
        ${budget ? `<p style="margin:0 0 4px;"><strong>Budget max :</strong> ${escapeHtml(budget)}</p>` : ""}
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Reçu le ${fmtDate(record.created_at)}</p>
      `,
    };
  }

  // Un collaborateur demande la mise en ligne d'un bien. Envoyé par le
  // déclencheur notifier_bien_a_valider(), avec le type A_VALIDER : sans cet
  // email, une annonce peut attendre des jours si personne n'ouvre le
  // portefeuille, et le collaborateur croit son bien en ligne.
  if (table === "properties") {
    const auteur = await fetchCollaborateur(record.owner_id);
    const nom = auteur?.display_name || auteur?.contact_name || "un collaborateur";
    const lieu = [record.commune, record.region].filter(Boolean).join(", ");
    const prix = fcfa(record.price);
    const resoumission = !!record.motif_refus_precedent;

    return {
      subject: `⏳ À valider — ${record.type} à ${record.commune || "—"} (${nom})`,
      html: `
        <h2 style="margin:0 0 4px;">Un bien attend votre autorisation</h2>
        <p style="margin:0 0 12px;color:#5C6470;font-size:13px;">
          Il n'apparaîtra <strong>pas</strong> sur la vitrine avant que vous ne l'autorisiez.
        </p>
        <p style="margin:0 0 4px;"><strong>Proposé par :</strong> ${escapeHtml(nom)}</p>
        <p style="margin:0 0 4px;"><strong>Référence :</strong> ${escapeHtml(record.ref)}</p>
        <p style="margin:0 0 4px;"><strong>Bien :</strong> ${escapeHtml(record.type)} — ${escapeHtml(record.operation)}${lieu ? ", " + escapeHtml(lieu) : ""}</p>
        ${prix ? `<p style="margin:0 0 4px;"><strong>Prix affiché :</strong> ${escapeHtml(prix)}</p>` : ""}
        ${record.surface ? `<p style="margin:0 0 4px;"><strong>Surface :</strong> ${escapeHtml(String(record.surface))} m²</p>` : ""}
        ${resoumission
          ? `<p style="margin:12px 0;padding:12px;background:#FDF3E3;border-radius:10px;font-size:13px;">
               Déjà refusé une première fois, motif : « ${escapeHtml(record.motif_refus_precedent)} ». À vérifier de nouveau.
             </p>`
          : ""}
        <p style="margin:16px 0 0;">
          <a href="https://pabbusiness221.github.io/PAB-Immo/Portefeuille-Immo.html"
             style="display:inline-block;padding:10px 16px;background:#161B22;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;">
            Ouvrir le portefeuille
          </a>
        </p>
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Demandé le ${fmtDate(record.soumis_le)}</p>
      `,
    };
  }

  return null;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  if (!RESEND_API_KEY || !NOTIFY_EMAIL) {
    console.error("RESEND_API_KEY ou NOTIFY_EMAIL manquant dans les secrets.");
    await journaliser("configuration", "echec", 0,
      "RESEND_API_KEY ou NOTIFY_EMAIL manquant dans les secrets.");
    return new Response("Missing configuration", { status: 500 });
  }

  let payload: any;
  try {
    payload = await req.json();
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const { type, table, record } = payload ?? {};

  if (!record) {
    return new Response("Ignored", { status: 200 });
  }

  // Deux familles d'événements, volontairement distinguées par leur type :
  //   INSERT    — un prospect s'est manifesté (3 tables de la vitrine) ;
  //   A_VALIDER — un collaborateur demande la mise en ligne d'un bien.
  // Le type propre évite d'élargir le filtre INSERT à properties, ce qui aurait
  // envoyé un email à chaque bien créé, y compris les brouillons.
  const attendu =
    (type === "INSERT" &&
      ["contact_messages", "appointments", "alert_subscriptions"].includes(table)) ||
    (type === "A_VALIDER" && table === "properties");

  if (!attendu) {
    return new Response("Ignored", { status: 200 });
  }

  const email = await buildEmail(table, record);
  if (!email) {
    return new Response("Nothing to send", { status: 200 });
  }

  // « properties » seul serait opaque dans le journal du portefeuille : la table
  // ne dit pas de quel événement il s'agit.
  const evenement = type === "A_VALIDER" ? "properties:a_valider" : table;

  const resendRes = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: Deno.env.get("NOTIFY_FROM") || "PAB Immo <onboarding@resend.dev>",
      to: [NOTIFY_EMAIL],
      subject: email.subject,
      html: `<div style="font-family:sans-serif;color:#161B22;max-width:480px;">${email.html}</div>`,
    }),
  });

  if (!resendRes.ok) {
    const errText = await resendRes.text();
    console.error("Échec envoi Resend:", errText);
    await journaliser(evenement, "echec", 0, `Resend ${resendRes.status} : ${errText}`);
    return new Response("Resend error: " + errText, { status: 502 });
  }

  await journaliser(evenement, "envoye", 1);
  return new Response("OK", { status: 200 });
});
