"use strict";

// Interface Agent TAG : lit et écrit uniquement via l'API (aucune donnée fictive côté client).

const etat = { app: null, effectifs: null, run: null, besoinChoisi: null };
const $ = (id) => document.getElementById(id);

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function utilisateur() { return $("utilisateur").value; }

// Conseils affichés après le message du serveur, selon le code de refus.
const CONSEILS = {
  DONNEES_MODIFIEES: "Cliquez sur « Recalculer » pour repartir des données actuelles.",
  RUN_NON_OUVERT: "Cliquez sur « Recalculer » pour obtenir de nouvelles propositions.",
  PROPOSITION_NON_ACTIVE: "La page a été rechargée avec l'état actuel.",
  PROPOSITION_PERIMEE: "La page a été rechargée avec l'état actuel.",
  MOTIF_REQUIS: "Saisissez un motif dans le champ prévu.",
  DONNEES_INCOMPLETES: "Importez les affectations et les absences de cette date, absences attestées.",
  RUN_DEJA_OUVERT: "Le calcul existant est affiché.",
  ROLE_NON_AUTORISE: "Choisissez en haut un utilisateur autorisé à décider.",
  CANDIDAT_RESERVE_AILLEURS: "Ce candidat est retenu pour une autre chaîne : choisissez-en un autre.",
  P1: "Le poste quitté serait dégarni : choisissez un autre candidat.",
  P3: "La chaîne donneuse a atteint son plafond de transferts.",
};

class ErreurApi extends Error {
  constructor(message, code) { super(message); this.code = code; }
}

async function api(chemin, options = {}) {
  let reponse;
  try {
    reponse = await fetch(chemin, {
      ...options,
      headers: { "Content-Type": "application/json", "X-Utilisateur": utilisateur(), ...(options.headers || {}) },
    });
  } catch (_) {
    throw new ErreurApi("Le serveur Agent TAG ne répond pas. Vérifiez qu'il est démarré, puis rechargez la page.", "RESEAU");
  }
  const corps = await reponse.json().catch(() => ({}));
  if (!reponse.ok) {
    let message = corps.message;
    if (!message && Array.isArray(corps.detail)) message = "Requête invalide : " + corps.detail.map((d) => d.msg).join(" ; ");
    throw new ErreurApi(message || `Erreur ${reponse.status}`, corps.code);
  }
  return corps;
}

function annoncer(texte, ok = false, code = null) {
  const zone = $("message");
  zone.textContent = texte + (code && CONSEILS[code] ? " " + CONSEILS[code] : "");
  zone.className = "message" + (ok ? " ok" : "");
  zone.hidden = false;
  clearTimeout(annoncer.minuterie);
  annoncer.minuterie = setTimeout(() => { zone.hidden = true; }, ok ? 4000 : 10000);
}

function memoriser(cle, valeur) { try { localStorage.setItem("agent-tag." + cle, valeur); } catch (_) { /* facultatif */ } }
function relire(cle) { try { return localStorage.getItem("agent-tag." + cle); } catch (_) { return null; } }

function dateFr(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  return iso.length === 10 ? d.toLocaleDateString("fr-FR") : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });
}

const parametres = () => `date=${encodeURIComponent($("date").value)}&chaine=${encodeURIComponent($("chaine").value)}`;

// --- Initialisation ------------------------------------------------------------------------

async function demarrer() {
  try {
    etat.app = await api("/api/etat");
  } catch (e) {
    annoncer(e.message);
    $("titre-chaine").textContent = "Serveur injoignable";
    return;
  }
  const { environnement, configuration, utilisateurs, chaines, dates } = etat.app;

  const env = $("environnement");
  env.textContent = environnement ? `Environnement ${environnement.usage} — ${environnement.libelle}` : "Environnement non initialisé";
  env.classList.toggle("test", Boolean(environnement && environnement.usage === "TEST"));

  const choix = $("utilisateur");
  choix.innerHTML = utilisateurs.map((u) => `<option value="${esc(u.identifiant)}">${esc(u.nom)} (${esc(u.role)})</option>`).join("");
  const memo = relire("utilisateur");
  if (memo && utilisateurs.some((u) => u.identifiant === memo)) choix.value = memo;
  choix.addEventListener("change", () => { memoriser("utilisateur", utilisateur()); if (etat.run) chargerRun(etat.run.run.id).catch((e) => annoncer(e.message)); });

  afficherAvertissement(configuration);

  $("chaine").innerHTML = chaines.map((c) => `<option value="${esc(c.id)}">${esc(c.id)} — ${esc(c.produit)} (priorité ${esc(c.priorite)})</option>`).join("");
  $("dates-disponibles").innerHTML = dates.map((d) => `<option value="${esc(d)}">`).join("");
  $("aide-dates").textContent = dates.length
    ? `Données journalières disponibles : ${dates.map(dateFr).join(", ")}. Pour toute autre date, l'état des ouvriers est inconnu et aucun calcul n'est possible.`
    : "Aucune donnée journalière importée : importez un classeur avant de lancer un calcul.";
  $("date").value = relire("date") || dates[0] || "";
  $("chaine").value = relire("chaine") || (chaines[0] && chaines[0].id) || "";

  $("selection").addEventListener("submit", (ev) => { ev.preventDefault(); afficherSelection(); });
  if ($("date").value && $("chaine").value) afficherSelection();
}

function afficherAvertissement(cfg) {
  const zone = $("avertissement");
  if (!cfg) {
    zone.hidden = false;
    zone.innerHTML = "<strong>Aucune configuration active.</strong> Aucun calcul n'est possible. Un administrateur doit installer une configuration (en TEST : <code>config-provisoire</code>).";
    return;
  }
  if (cfg.validee) { zone.hidden = true; return; }
  zone.hidden = false;
  const nonValides = Object.entries(cfg.indicateurs).filter(([, v]) => !v).map(([k]) => k).join(", ");
  zone.innerHTML = `<strong>${esc(cfg.avertissement)}</strong> Configuration ${esc(cfg.version)} « ${esc(cfg.libelle)} » :
    P1 = ${esc(cfg.m_bloc)}, P2 = ${esc(cfg.m_alerte)}, P3 = ${esc(cfg.p3)}. Non validés : ${esc(nonValides)}.`;
}

// --- Chargements ---------------------------------------------------------------------------

async function afficherSelection() {
  const date = $("date").value, chaine = $("chaine").value;
  if (!date || !chaine) { annoncer("Choisissez une date et une chaîne."); return; }
  memoriser("date", date); memoriser("chaine", chaine);
  etat.besoinChoisi = null;
  try {
    await rafraichir();
  } catch (e) { annoncer(e.message, false, e.code); }
}

async function rafraichir() {
  etat.effectifs = await api(`/api/effectifs?${parametres()}`);
  afficherEffectifs();
  const runs = await api(`/api/runs?${parametres()}`);
  const courant = (etat.run && runs.find((r) => r.id === etat.run.run.id)) || runs.find((r) => r.statut !== "CLOS") || runs[0];
  if (courant) await chargerRun(courant.id);
  else { etat.run = null; afficherRun(); }
  await Promise.all([chargerEngagements(), chargerImports(), chargerHistorique()]);
}

async function chargerRun(id) {
  etat.run = await api(`/api/runs/${id}`);
  afficherRun();
}

// --- Effectifs -----------------------------------------------------------------------------

const LIBELLES_ETAT = { DISPONIBLE: "Disponibles", ABSENT: "Absents", INDETERMINE: "Indéterminés", INCONNU: "Inconnus" };

function donneesAbsentes() {
  const eff = etat.effectifs;
  return !eff || eff.ouvriers.every((o) => o.etat === "INCONNU");
}

function afficherEffectifs() {
  const eff = etat.effectifs;
  $("titre-chaine").textContent = `Chaîne ${eff.chaine} le ${dateFr(eff.date)}`;
  $("synthese").innerHTML = Object.keys(LIBELLES_ETAT).map((k) =>
    `<div><dd>${eff.synthese[k] || 0}</dd><dt><span class="legende-carreau ${k}"></span>${LIBELLES_ETAT[k]}</dt></div>`).join("");
  $("chaine-vide").hidden = !donneesAbsentes();
  const parPoste = new Map();
  for (const o of eff.ouvriers) {
    if (!parPoste.has(o.poste)) parPoste.set(o.poste, []);
    parPoste.get(o.poste).push(o);
  }
  $("bande").innerHTML = [...parPoste.entries()].map(([poste, liste]) => `
    <div class="poste"><h3>${esc(poste)}</h3><div class="carreaux">
      ${liste.map((o) => `<span class="carreau ${esc(o.etat)}" title="${esc(o.id)} ${esc(o.nom)} — ${esc(o.etat)} (${esc(o.cause)})">${esc(o.id)}</span>`).join("")}
    </div></div>`).join("");
}

// --- Calcul et besoins ----------------------------------------------------------------------

function statutBesoin(b) {
  if (b.remplacement && b.remplacement.statut_revue === "A_REVOIR") return ["a-revoir", "Confirmé, à revoir"];
  switch (b.statut) {
    case "EN_ATTENTE": return ["proposition", "Proposition à confirmer"];
    case "POURVU": return ["confirme", "Remplacement confirmé"];
    case "BLOQUE": return ["bloque", "Bloqué : exigence manquante"];
    case "A_TRAITER": return ["neutre", "À recalculer"];
    case "NON_POURVU":
      if ((b.cause || "").startsWith("AUCUN_CANDIDAT")) return ["sans-candidat", "Sans candidat conforme"];
      if ((b.cause || "").startsWith("DECISION")) return ["neutre", "Laissé non pourvu"];
      if ((b.cause || "").startsWith("CLOTURE")) return ["neutre", "Non pourvu (calcul clos)"];
      if ((b.cause || "").startsWith("ABSENCE_NON_CONFIRMEE")) return ["neutre", "Plus d'absence confirmée"];
      return ["neutre", "Non pourvu"];
    default: return ["neutre", b.statut];
  }
}

function afficherRun() {
  const actions = $("actions-calcul");
  const det = etat.run;
  const tbody = document.querySelector("#table-besoins tbody");
  $("bandeau-reimport").hidden = true;
  if (!det) {
    const sansDonnees = donneesAbsentes();
    $("resume-calcul").textContent = sansDonnees
      ? "Aucune donnée d'affectation n'est importée pour cette date : le calcul est impossible. Importez les affectations et les absences du jour (absences attestées)."
      : "Aucun calcul pour cette date et cette chaîne.";
    $("alerte-combinaison").hidden = true;
    $("raison-decision").hidden = true;
    tbody.innerHTML = "";
    $("besoins-vide").textContent = sansDonnees ? "" : "Lancez le calcul pour identifier les besoins et les candidats.";
    $("detail").innerHTML = "";
    actions.innerHTML = `<button type="button" id="bouton-lancer"${sansDonnees ? " disabled" : ""}>Lancer le calcul des remplacements</button>`;
    $("bouton-lancer").addEventListener("click", lancer);
    return;
  }
  const r = det.run, it = det.iteration;
  const statutRun = { OUVERT: "ouvert", A_RECALCULER: "à recalculer", CLOS: "clos" }[r.statut];
  let resume = `Calcul ${r.id}, ${statutRun}, lancé par ${r.cree_par} le ${dateFr(r.date_creation)}.`;
  if (it) resume += ` Itération ${it.numero} (${it.declencheur.toLowerCase().replaceAll("_", " ")}) : ${it.couverture_sequentielle} proposition(s) pour ${it.besoins_consideres} besoin(s) à traiter ; couverture maximale possible : ${it.couverture_maximale}.`;
  if (r.statut === "CLOS") resume += ` Clos le ${dateFr(r.date_cloture)} par ${r.clos_par} : ${r.motif_cloture}.`;
  $("resume-calcul").textContent = resume;

  const bandeau = $("bandeau-reimport");
  const reimp = det.reimports;
  if (r.statut === "A_RECALCULER" || reimp.remplacements_a_revoir) {
    let texte = "";
    if (r.statut === "A_RECALCULER") {
      texte = r.cause_statut === "DONNEES_MODIFIEES"
        ? "Les données de cette date ont été réimportées : les propositions en attente ont été annulées. Cliquez sur « Recalculer »."
        : `Le calcul doit être relancé (${esc(r.cause_statut || "?")}). Cliquez sur « Recalculer ».`;
    }
    if (reimp.lots.length) texte += " " + reimp.lots.map((l) => `Lot ${l.lot} (${dateFr(l.applique_le)}) : ${l.propositions_annulees} proposition(s) annulée(s).`).join(" ");
    if (reimp.remplacements_a_revoir) texte += ` ${reimp.remplacements_a_revoir} remplacement(s) confirmé(s) à revoir : ils ne sont pas annulés automatiquement, une décision est nécessaire.`;
    bandeau.textContent = texte.trim();
    bandeau.hidden = false;
  }

  const alerte = $("alerte-combinaison");
  alerte.hidden = !(it && it.alerte_combinaison && r.statut === "OUVERT");
  if (!alerte.hidden) {
    alerte.textContent = `Une meilleure combinaison couvrirait ${it.couverture_maximale} besoins au lieu de ${it.couverture_sequentielle}. Exemple : ${Object.entries(it.combinaison_maximale).map(([a, o]) => a + " ← " + o).join(", ")}. Utilisez « Choisir ce candidat » pour réarbitrer.`;
  }
  const raison = $("raison-decision");
  raison.hidden = det.decision.possible;
  raison.textContent = det.decision.possible ? "" : "Confirmations et refus indisponibles : " + det.decision.raison + ".";

  actions.innerHTML = r.statut === "CLOS"
    ? `<button type="button" id="bouton-lancer">Lancer un nouveau calcul</button>`
    : `<button type="button" class="${r.statut === "A_RECALCULER" ? "" : "secondaire"}" id="bouton-recalculer">Recalculer</button>
       <button type="button" class="danger" id="bouton-cloturer">Clôturer le calcul</button>`;
  if (r.statut === "CLOS") $("bouton-lancer").addEventListener("click", lancer);
  else {
    $("bouton-recalculer").addEventListener("click", () => operation(`/api/runs/${r.id}/recalculer`, {}, "Calcul relancé."));
    $("bouton-cloturer").addEventListener("click", afficherCloture);
  }

  $("besoins-vide").textContent = det.besoins.length ? "" : "Aucun besoin : aucun absent confirmé sur cette chaîne à cette date.";
  tbody.innerHTML = det.besoins.map((b) => {
    const [classe, libelle] = statutBesoin(b);
    const qui = b.remplacement ? `${esc(b.remplacement.ouvrier)} <span class="nom-petit">${esc(b.remplacement.nom)}</span>`
      : b.proposition ? `${esc(b.proposition.ouvrier)} <span class="nom-petit">${esc(b.proposition.nom)} (réservé)</span>` : "—";
    return `<tr data-besoin="${b.id}" aria-selected="${b.id === etat.besoinChoisi}" tabindex="0">
      <td><span class="id">${esc(b.absent)}</span><span class="nom-petit">${esc(b.nom_absent)}</span></td>
      <td>${esc(b.poste)}${b.critique ? ' <span class="critique">critique</span>' : ""}</td>
      <td><span class="etat ${classe}">${esc(libelle)}</span></td>
      <td>${qui}</td></tr>`;
  }).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    const choisir = () => { etat.besoinChoisi = Number(tr.dataset.besoin); afficherRun(); };
    tr.addEventListener("click", choisir);
    tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); choisir(); } });
  });
  if (!det.besoins.some((b) => b.id === etat.besoinChoisi) && det.besoins.length) {
    etat.besoinChoisi = det.besoins[0].id;
    afficherRun();
    return;
  }
  afficherDetail();
}

function afficherCloture() {
  $("detail").innerHTML = `<h3>Clôturer le calcul ${etat.run.run.id}</h3>
    <p class="exigence">Les propositions non confirmées sont annulées et les besoins restants passent en « non pourvu ». Les remplacements confirmés sont conservés.</p>
    <div class="formulaire"><label for="motif-cloture">Motif (obligatoire)</label>
      <textarea id="motif-cloture"></textarea>
      <div class="ligne"><button type="button" class="danger" id="valider-cloture">Clôturer</button>
      <button type="button" class="secondaire" id="annuler-cloture">Revenir</button></div></div>`;
  $("annuler-cloture").addEventListener("click", afficherDetail);
  $("valider-cloture").addEventListener("click", () => operation(`/api/runs/${etat.run.run.id}/cloturer`, { motif: $("motif-cloture").value }, "Calcul clôturé."));
}

const LIBELLES_DECISION = {
  ACCEPTER: "Remplacement confirmé", CHOISIR_AUTRE: "Autre candidat choisi et confirmé",
  REFUSER: "Proposition refusée", LAISSER_NON_POURVU: "Laissé non pourvu", ROUVRIR: "Besoin rouvert",
  ANNULER_REMPLACEMENT: "Remplacement annulé", CONFIRMER_APRES_REIMPORT: "Maintenu après réimport",
};

function afficherDetail() {
  const det = etat.run;
  const zone = $("detail");
  const b = det && det.besoins.find((x) => x.id === etat.besoinChoisi);
  if (!b) { zone.innerHTML = ""; return; }
  const ouvert = det.run.statut === "OUVERT";
  const peut = det.decision.possible;
  const [classe, libelle] = statutBesoin(b);
  const champMotif = (id, libelleMotif) => `<label for="${id}">${libelleMotif}</label><textarea id="${id}"></textarea>`;
  let html = `<h3>${esc(b.absent)} ${esc(b.nom_absent)} — ${esc(b.poste)}</h3>
    <p class="exigence">${b.competence ? `Exigence : ${esc(b.competence)}, niveau ${esc(b.niveau_min) || "non défini"} au minimum.` : "Aucune exigence enregistrée pour ce poste."} ${b.critique ? "Compétence critique pour la chaîne." : ""}</p>`;

  if (b.statut === "BLOQUE") {
    html += `<div class="encadre bloque"><p class="titre">Besoin bloqué</p><p>${esc(b.cause)}</p>
      <p class="explication">Aucun candidat n'est proposé tant que l'exigence du poste n'est pas définie par le responsable métier (décisions D2, D7). Aucune valeur n'est déduite.</p></div>`;
  } else if (b.remplacement) {
    const rp = b.remplacement;
    html += `<div class="encadre ${classe}"><p class="titre">${esc(libelle)} : ${esc(rp.ouvrier)} ${esc(rp.nom)}</p>
      <p>Confirmé le ${dateFr(rp.confirme_le)} par ${esc(rp.confirme_par)}${rp.usage === "TEST" ? ' <span class="marque-test">(décision de TEST)</span>' : ""}. L'ouvrier est engagé pour la journée.</p>
      <p>Quitte ${esc(rp.poste)} sur ${esc(rp.chaine)} — risque <span class="risque-${esc(rp.risque)}">${esc(rp.risque)}</span>.</p>
      ${rp.statut_revue === "A_REVOIR" ? `<p><strong>À revoir après réimport :</strong> ${esc(rp.cause_revue)}. Maintenez-le seulement s'il reste conforme, sinon annulez-le.</p>` : ""}
      ${peut && det.run.statut !== "CLOS" ? `<div class="formulaire">${champMotif("motif-annulation", "Motif (obligatoire pour annuler ou maintenir)")}
        <label class="ligne"><input type="checkbox" id="exclure"> Ne plus proposer cet ouvrier pour ce besoin</label>
        <div class="ligne"><button type="button" class="danger" id="annuler-remplacement">Annuler le remplacement</button>
        ${rp.statut_revue === "A_REVOIR" ? '<button type="button" class="secondaire" id="confirmer-revue">Maintenir après vérification</button>' : ""}</div></div>` : ""}
    </div>`;
  } else if (b.proposition) {
    const p = b.proposition;
    html += `<div class="encadre proposition"><p class="titre">Proposition : ${esc(p.ouvrier)} ${esc(p.nom)}</p>
      <p>Réservé pour ce besoin, non affecté. Quitte ${esc(p.poste)} sur ${esc(p.chaine)} — risque <span class="risque-${esc(p.risque)}">${esc(p.risque)}</span>.</p>
      <p class="explication">${esc(p.explication)}</p>
      ${ouvert && peut ? `<div class="formulaire">
        <div class="ligne"><button type="button" class="confirmer" id="accepter">Confirmer le remplacement</button></div>
        ${champMotif("motif-decision", "Motif (obligatoire pour refuser, choisir un autre candidat ou laisser non pourvu)")}
        <div class="ligne"><button type="button" class="danger" id="refuser">Refuser la proposition</button>
        <button type="button" class="secondaire" id="non-pourvu">Laisser non pourvu</button></div></div>` : ""}
    </div>`;
  } else {
    const rouvrable = b.statut === "NON_POURVU" && ouvert && peut;
    html += `<div class="encadre ${classe}"><p class="titre">${esc(libelle)}</p><p>${esc(b.cause || "")}</p>
      ${rouvrable ? `<div class="formulaire">${champMotif("motif-rouvrir", "Motif (obligatoire pour rouvrir)")}
        <div class="ligne"><button type="button" class="secondaire" id="rouvrir">Rouvrir le besoin</button></div></div>` : ""}</div>`;
  }

  if (b.decisions.length) {
    html += `<div class="decisions-besoin"><p class="titre">Décisions sur ce besoin</p><ul>${b.decisions.map((d) =>
      `<li>${dateFr(d.horodatage)} — ${esc(LIBELLES_DECISION[d.type] || d.type)}${d.ouvrier ? " (" + esc(d.ouvrier) + ")" : ""} par ${esc(d.auteur)}${d.motif ? " : « " + esc(d.motif) + " »" : ""}</li>`).join("")}</ul></div>`;
  }

  const eligibles = b.candidats.filter((c) => c.eligible);
  const rejetes = b.candidats.filter((c) => !c.eligible);
  const peutChoisir = Boolean(b.proposition) && ouvert && peut;
  if (b.candidats.length) {
    const ligneCandidat = (c) => {
      const propose = b.proposition && c.ouvrier === b.proposition.ouvrier;
      const action = peutChoisir && !propose ? `<button type="button" class="petit secondaire" data-choisir="${esc(c.ouvrier)}">Choisir ce candidat</button>` : propose ? '<span class="nom-petit">proposé</span>' : "";
      return `<tr><td>${c.rang}${c.ex_aequo ? " =" : ""}</td>
        <td><span class="id">${esc(c.ouvrier)}</span><span class="nom-petit">${esc(c.nom)}</span></td>
        <td>${esc(c.poste)} (${esc(c.chaine)}), ${esc(c.restants)} restant(s)</td>
        <td class="risque-${esc(c.risque)}">${esc(c.risque)}</td><td>${action}</td></tr>
        <tr><td></td><td colspan="4" class="explication">${esc(c.explication)}</td></tr>`;
    };
    const entete = "<thead><tr><th>Rang</th><th>Ouvrier</th><th>Quitte</th><th>Risque</th><th></th></tr></thead>";
    html += `<div class="defile"><table><caption>Candidats classés (itération ${esc(b.iteration_evaluation)}) : ${eligibles.length} admissible(s)</caption>
      ${entete}<tbody>${eligibles.slice(0, 5).map(ligneCandidat).join("") || '<tr><td colspan="5" class="vide">Aucun candidat conforme aux règles.</td></tr>'}
      </tbody></table></div>`;
    if (eligibles.length > 5) {
      html += `<details class="voir-plus"><summary>Voir les ${eligibles.length - 5} autres candidats admissibles</summary>
        <div class="defile"><table>${entete}<tbody>${eligibles.slice(5).map(ligneCandidat).join("")}</tbody></table></div></details>`;
    }
    if (rejetes.length) {
      const resume = Object.entries(b.rejets).map(([k, n]) => `${esc(k)} ×${n} (${esc(det.libelles_controles[k] || k)})`).join(" ; ");
      html += `<details class="ecartes"><summary>${rejetes.length} candidat(s) écarté(s)</summary><p class="explication">${resume}</p>
        <table><tbody>${rejetes.map((c) => `<tr><td class="id">${esc(c.ouvrier)}</td><td class="explication">${esc(c.explication)}</td></tr>`).join("")}</tbody></table></details>`;
    }
  } else if (b.statut !== "BLOQUE" && !b.remplacement) {
    html += `<p class="vide">Aucun candidat évalué pour ce besoin à la dernière itération.</p>`;
  }
  zone.innerHTML = html;

  const lier = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", fn); };
  const motif = (id) => ($(id) ? $(id).value : "");
  lier("accepter", () => operation(`/api/propositions/${b.proposition.id}/accepter`, {}, `Remplacement de ${b.absent} par ${b.proposition.ouvrier} confirmé.`));
  lier("refuser", () => operation(`/api/propositions/${b.proposition.id}/refuser`, { motif: motif("motif-decision") }, "Proposition refusée ; nouveau calcul effectué."));
  lier("non-pourvu", () => operation(`/api/besoins/${b.id}/laisser-non-pourvu`, { motif: motif("motif-decision") }, "Besoin laissé non pourvu."));
  lier("rouvrir", () => operation(`/api/besoins/${b.id}/rouvrir`, { motif: motif("motif-rouvrir") }, "Besoin rouvert ; nouveau calcul effectué."));
  lier("annuler-remplacement", () => operation(`/api/remplacements/${b.remplacement.id}/annuler`,
    { motif: motif("motif-annulation"), exclure_ouvrier: $("exclure").checked }, "Remplacement annulé ; nouveau calcul effectué."));
  lier("confirmer-revue", () => operation(`/api/remplacements/${b.remplacement.id}/confirmer-apres-reimport`,
    { motif: motif("motif-annulation") }, "Remplacement maintenu."));
  zone.querySelectorAll("[data-choisir]").forEach((bouton) => bouton.addEventListener("click", () => {
    const ouvrier = bouton.dataset.choisir;
    operation(`/api/propositions/${b.proposition.id}/choisir-autre`, { id_ouvrier: ouvrier, motif: motif("motif-decision") },
      `${ouvrier} choisi et confirmé pour remplacer ${b.absent}.`);
  }));
}

async function lancer() {
  const corps = { date: $("date").value, chaine: $("chaine").value };
  try {
    const det = await api("/api/runs", { method: "POST", body: JSON.stringify(corps) });
    etat.run = det; etat.besoinChoisi = null;
    afficherRun();
    await Promise.all([chargerEngagements(), chargerHistorique()]);
    annoncer(`Calcul ${det.run.id} effectué : ${det.iteration.couverture_sequentielle} proposition(s) à examiner.`, true);
  } catch (e) {
    annoncer(e.message, false, e.code);
    if (e.code === "RUN_DEJA_OUVERT") afficherSelection();
  }
}

async function operation(chemin, corps, succes) {
  const boutons = document.querySelectorAll("#detail button, #actions-calcul button");
  boutons.forEach((b) => { b.disabled = true; });
  try {
    await api(chemin, { method: "POST", body: JSON.stringify(corps) });
  } catch (e) {
    annoncer(e.message, false, e.code);
    if (["PROPOSITION_NON_ACTIVE", "PROPOSITION_PERIMEE", "RUN_NON_OUVERT"].includes(e.code)) {
      await rafraichir().catch(() => {});
    } else {
      boutons.forEach((b) => { b.disabled = false; });   // la saisie en cours est conservée
    }
    return;
  }
  try {
    await rafraichir();
    annoncer(succes, true);
  } catch (e) { annoncer(e.message, false, e.code); }
}

// --- Réservations, imports, historique -----------------------------------------------------

async function chargerEngagements() {
  const liste = await api(`/api/engagements?date=${encodeURIComponent($("date").value)}`);
  $("engagements-vide").textContent = liste.length ? "" : "Aucun ouvrier réservé ni engagé à cette date.";
  document.querySelector("#table-engagements tbody").innerHTML = liste.map((e) => `<tr>
    <td><span class="id">${esc(e.ouvrier)}</span><span class="nom-petit">${esc(e.nom)}</span></td>
    <td>${e.type === "ENGAGE" ? `<span class="etat confirme">Engagé${e.revue === "A_REVOIR" ? " — à revoir" : ""}</span>` : '<span class="etat proposition">Réservé (proposition)</span>'}</td>
    <td>${esc(e.absent)} <span class="nom-petit">${esc(e.nom_absent)}</span></td>
    <td>${esc(e.chaine_cible)} (calcul ${esc(e.run)})</td>
    <td>${esc(e.poste_quitte)} sur ${esc(e.chaine_donneuse)}</td>
    <td>${dateFr(e.depuis)}</td></tr>`).join("");
}

async function chargerImports() {
  const liste = await api(`/api/imports?date=${encodeURIComponent($("date").value)}`);
  $("imports-vide").textContent = liste.length ? "" : "Aucune donnée journalière importée pour cette date.";
  document.querySelector("#table-imports tbody").innerHTML = liste.map((l) => `<tr>
    <td>Lot ${esc(l.lot)}</td><td>${esc(l.fichier)}</td><td>${dateFr(l.applique_le || l.horodatage)} par ${esc(l.auteur)}</td>
    <td>${l.courant ? '<span class="etat confirme">En vigueur</span>' : '<span class="etat neutre">Remplacé</span>'}</td>
    <td>${esc(l.chaines)}</td>
    <td>${l.propositions_annulees ? `${l.propositions_annulees} proposition(s) annulée(s)` : "—"}${l.remplacements_a_revoir ? `, ${l.remplacements_a_revoir} remplacement(s) à revoir` : ""}</td></tr>`).join("");
}

async function chargerHistorique() {
  const liste = await api(`/api/decisions?${parametres()}`);
  $("historique-vide").textContent = liste.length ? "" : "Aucune décision pour cette date et cette chaîne.";
  document.querySelector("#table-historique tbody").innerHTML = liste.map((d) => `<tr>
    <td>${dateFr(d.horodatage)}</td><td>${esc(LIBELLES_DECISION[d.type] || d.type)}${d.exclure_ouvrier ? " (ouvrier exclu)" : ""}</td>
    <td>${esc(d.absent)} <span class="nom-petit">${esc(d.nom_absent)}</span></td>
    <td>${esc(d.ouvrier || "—")} <span class="nom-petit">${esc(d.nom_ouvrier || "")}</span></td>
    <td>${esc(d.motif || "—")}</td><td>${esc(d.auteur)}</td>
    <td>${d.usage === "TEST" || !d.configuration_validee ? '<span class="marque-test">TEST, non valable en réel</span>' : "réelle"}</td></tr>`).join("");
}

demarrer();
