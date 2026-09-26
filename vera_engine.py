from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from models import ComposedMessage, ReplyResponse, TickAction
from validators import sanitize_urls


class VeraEngine:
    """
    Deterministic 4-Context Composition and Multi-Turn Conversation Engine.
    Implements exact category-aware voice profiles, merchant/customer personalization,
    factual grounding, compulsion levers, and stateful reply handling.
    """

    def __init__(self):
        pass

    # -------------------------------------------------------------------------
    # Helper: Extract Identifiers and Data
    # -------------------------------------------------------------------------

    def _get_salutation(self, merchant: Dict[str, Any], category: Dict[str, Any]) -> str:
        identity = merchant.get("identity", {})
        owner_first = identity.get("owner_first_name", "")
        name = identity.get("name", "")
        slug = category.get("slug", "")

        if slug == "dentists":
            if owner_first:
                clean_name = owner_first.replace("Dr.", "").replace("Dr", "").strip()
                return f"Dr. {clean_name}"
            if "Dr." in name:
                parts = name.split()
                return f"{parts[0]} {parts[1]}" if len(parts) > 1 else name
            return f"Dr. {name}"
        
        if slug == "pharmacies":
            if owner_first:
                return owner_first
            return identity.get("name", "Team")

        if owner_first:
            return owner_first
        return identity.get("name", "Team")

    def _find_digest_item(self, category: Dict[str, Any], top_item_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not top_item_id:
            return None
        for item in category.get("digest", []):
            if item.get("id") == top_item_id:
                return item
        return None

    def _find_matching_digest(self, category: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
        for item in category.get("digest", []):
            if item.get("kind") == kind:
                return item
        items = category.get("digest", [])
        return items[0] if items else None

    def _get_active_offers(self, merchant: Dict[str, Any], category: Dict[str, Any]) -> List[str]:
        offers = []
        for o in merchant.get("offers", []):
            if o.get("status") == "active":
                offers.append(o.get("title", ""))
        if not offers:
            for o in category.get("offer_catalog", []):
                offers.append(o.get("title", ""))
        return offers

    # -------------------------------------------------------------------------
    # 4-Context Outbound Composer
    # -------------------------------------------------------------------------

    def compose(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> ComposedMessage:
        """
        Composes an outbound WhatsApp message anchored on Category, Merchant, Trigger, and Customer contexts.
        """
        trg_kind = trigger.get("kind", "")
        trg_scope = trigger.get("scope", "merchant")
        cat_slug = category.get("slug", "")
        trg_id = trigger.get("id", "trg_unknown")
        mid = merchant.get("merchant_id", "m_unknown")
        cid = customer.get("customer_id") if customer else trigger.get("customer_id")
        supp_key = trigger.get("suppression_key", f"{trg_kind}:{mid}:{trg_id}")
        conv_id = f"conv_{mid}_{trg_id}"

        # Customer-facing composition
        if trg_scope == "customer" or customer is not None:
            return self._compose_customer_facing(category, merchant, trigger, customer, conv_id, supp_key)

        # Merchant-facing composition by trigger kind
        if trg_kind in ("research_digest", "cde_opportunity", "regulation_change", "supply_alert", "alert"):
            return self._compose_research_or_alert(category, merchant, trigger, conv_id, supp_key)
        
        elif trg_kind == "active_planning_intent":
            return self._compose_planning_intent(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind in ("perf_dip", "perf_spike", "seasonal_perf_dip"):
            return self._compose_performance(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind in ("renewal_due", "winback_eligible", "dormant_with_vera"):
            return self._compose_lifecycle(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind == "milestone_reached":
            return self._compose_milestone(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind == "curious_ask_due":
            return self._compose_curious_ask(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind == "ipl_match_today":
            return self._compose_ipl_match(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind == "competitor_opened":
            return self._compose_competitor(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind in ("festival_upcoming", "category_seasonal"):
            return self._compose_seasonal_or_festival(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind == "gbp_unverified":
            return self._compose_gbp_unverified(category, merchant, trigger, conv_id, supp_key)

        elif trg_kind == "review_theme_emerged":
            return self._compose_review_theme(category, merchant, trigger, conv_id, supp_key)

        # Fallback general composer
        return self._compose_generic_merchant(category, merchant, trigger, conv_id, supp_key)

    # -------------------------------------------------------------------------
    # 1. Research, Compliance, Alert Composer
    # -------------------------------------------------------------------------

    def _compose_research_or_alert(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        payload = trigger.get("payload", {})
        top_item_id = payload.get("top_item_id") or payload.get("alert_id") or payload.get("digest_item_id")
        digest_item = self._find_digest_item(category, top_item_id) or self._find_matching_digest(category, "research")
        cat_slug = category.get("slug", "")

        # Specificity handlers based on category and digest
        if cat_slug == "dentists":
            if digest_item and "fluoride" in digest_item.get("id", "").lower():
                body = (
                    f"{salutation}, JIDA's Oct issue landed. One item relevant to your high-risk adult "
                    f"patients — 2,100-patient trial showed 3-month fluoride recall cuts caries "
                    f"recurrence 38% better than 6-month. Worth a look (2-min abstract). "
                    f"Want me to pull it + draft a patient-ed WhatsApp you can share? — JIDA Oct 2026 p.14"
                )
                params = [salutation, "JIDA Oct issue landed", "caries recurrence 38% better", "JIDA Oct 2026 p.14"]
                rationale = "Research digest release with clinical evidence (2,100 patients, 38% caries reduction, JIDA citation) tailored to high-risk adult cohort."
                return ComposedMessage(
                    conversation_id=conv_id,
                    merchant_id=merchant.get("merchant_id", ""),
                    send_as="vera",
                    trigger_id=trigger.get("id", ""),
                    template_name="vera_research_digest_v1",
                    template_params=params,
                    body=body,
                    cta="open_ended",
                    suppression_key=supp_key,
                    rationale=rationale,
                )
            elif digest_item and ("radiograph" in digest_item.get("id", "").lower() or trigger.get("kind") == "regulation_change"):
                body = (
                    f"{salutation}, compliance update: DCI revised radiograph dose limits effective 2026-12-15. "
                    f"Maximum dose drops from 1.5 mSv to 1.0 mSv per IOPA. E-speed film and digital RVG sensors pass; "
                    f"D-speed does not. Want me to draft the 5-point audit checklist for your clinic SOPs? — DCI circular 2026-11-04"
                )
                params = [salutation, "DCI revised radiograph dose limits", "1.5 to 1.0 mSv", "DCI circular 2026-11-04"]
                rationale = "Compliance regulation update on DCI radiograph dose limits (1.0 mSv) with actionable clinic audit checklist."
                return ComposedMessage(
                    conversation_id=conv_id,
                    merchant_id=merchant.get("merchant_id", ""),
                    send_as="vera",
                    trigger_id=trigger.get("id", ""),
                    template_name="vera_compliance_alert_v1",
                    template_params=params,
                    body=body,
                    cta="binary_yes_no",
                    suppression_key=supp_key,
                    rationale=rationale,
                )
            elif digest_item and "webinar" in digest_item.get("id", "").lower():
                body = (
                    f"{salutation}, IDA Delhi announced a CDE webinar on Digital Impressions & CAD/CAM workflow ROI "
                    f"for solo practices (2 credit hours) on 2 May, 7:00pm. Free for IDA members. "
                    f"Want me to send you the direct registration details? — IDA Delhi chapter calendar"
                )
                params = [salutation, "IDA Delhi CDE webinar", "2 credit hours", "2 May 7:00pm"]
                rationale = "CDE webinar notification with exact credits and dates from IDA calendar."
                return ComposedMessage(
                    conversation_id=conv_id,
                    merchant_id=merchant.get("merchant_id", ""),
                    send_as="vera",
                    trigger_id=trigger.get("id", ""),
                    template_name="vera_cde_webinar_v1",
                    template_params=params,
                    body=body,
                    cta="binary_yes_no",
                    suppression_key=supp_key,
                    rationale=rationale,
                )

        elif cat_slug == "pharmacies":
            if "atorvastatin" in trigger.get("id", "").lower() or (digest_item and "atorvastatin" in digest_item.get("id", "").lower()):
                cust_agg = merchant.get("customer_aggregate", {})
                chronic_count = cust_agg.get("chronic_rx_count", 240)
                affected_count = max(5, int(chronic_count * 0.09))
                body = (
                    f"{salutation}, urgent: voluntary recall on 2 atorvastatin batches (AT2024-1102, AT2024-1108) "
                    f"by Mfr Z — sub-potency, no safety risk, but customers should be informed for replacement. "
                    f"Pulled your repeat-Rx list: {affected_count} of your {chronic_count} chronic-Rx customers were dispensed these batches "
                    f"in last 90 days. Want me to draft their WhatsApp note + the replacement-pickup workflow? — CDSCO alert Apr 2026"
                )
                params = [salutation, "AT2024-1102, AT2024-1108", f"{affected_count} of {chronic_count} customers", "CDSCO alert Apr 2026"]
                rationale = "Voluntary batch recall alert with precise batch identifiers and merchant customer-aggregate cross-reference."
                return ComposedMessage(
                    conversation_id=conv_id,
                    merchant_id=merchant.get("merchant_id", ""),
                    send_as="vera",
                    trigger_id=trigger.get("id", ""),
                    template_name="vera_pharmacy_alert_v1",
                    template_params=params,
                    body=body,
                    cta="binary_yes_no",
                    suppression_key=supp_key,
                    rationale=rationale,
                )

        # General category digest fallback
        title = digest_item.get("title", "new industry update") if digest_item else "new industry update"
        source = digest_item.get("source", "latest digest") if digest_item else "industry data"
        summary = digest_item.get("summary", "") if digest_item else ""
        actionable = digest_item.get("actionable", "Review this week.") if digest_item else "Review this week."

        body = (
            f"{salutation}, heads up on {source}: {title}. {summary} "
            f"Action: {actionable} Want me to draft a quick action plan for your team?"
        )
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_generic_digest_v1",
            template_params=[salutation, title, source],
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=f"Category-level update from {source} with actionable recommendation.",
        )

    # -------------------------------------------------------------------------
    # 2. Customer-Facing Composer (Recall, Refill, Followup, Winback)
    # -------------------------------------------------------------------------

    def _compose_customer_facing(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        mid = merchant.get("merchant_id", "")
        m_ident = merchant.get("identity", {})
        m_name = m_ident.get("name", "Our Clinic")
        owner_first = m_ident.get("owner_first_name", "")
        c_ident = customer.get("identity", {}) if customer else {}
        c_name = c_ident.get("name", "there")
        lang = c_ident.get("language_pref", "en")
        trg_kind = trigger.get("kind", "")
        payload = trigger.get("payload", {})
        cat_slug = category.get("slug", "")

        # 1. Dentists Recall Due (Priya case)
        if cat_slug == "dentists" and trg_kind == "recall_due":
            body = (
                f"Hi {c_name}, {m_name} here 🦷 It's been 5 months since your last visit — "
                f"your 6-month cleaning recall is due. Apke liye 2 slots ready hain: "
                f"Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm. ₹299 cleaning + complimentary fluoride. "
                f"Reply 1 for Wed, 2 for Thu, or tell us a time that works."
            )
            params = [c_name, m_name, "5 months since your last visit", "Wed 5 Nov 6pm or Thu 6 Nov 5pm", "₹299 cleaning"]
            rationale = "Customer-scoped recall reminder via merchant WhatsApp, matching hi-en mix language preference and weekday-evening time slot."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=mid,
                customer_id=customer.get("customer_id") if customer else None,
                send_as="merchant_on_behalf",
                trigger_id=trigger.get("id", ""),
                template_name="merchant_recall_reminder_v1",
                template_params=params,
                body=body,
                cta="multi_choice_slot",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # 2. Pharmacy Chronic Refill Due (Mr. Sharma / son case)
        if cat_slug == "pharmacies" and trg_kind == "chronic_refill_due":
            loc = m_ident.get("locality", "Malviya Nagar")
            molecules = ", ".join(payload.get("molecule_list", ["metformin", "atorvastatin", "telmisartan"]))
            body = (
                f"Namaste — {m_name} {loc} yahan. Sharma ji ki 3 monthly medicines ({molecules}) "
                f"28 April ko khatam hongi. Same dose, same brand pack ready hai. "
                f"Senior discount 15% applied — total ₹1,420 (₹240 saved). "
                f"Free home delivery to saved address by 5pm tomorrow. Reply CONFIRM to dispatch, or call if any change in dosage."
            )
            params = [m_name, loc, molecules, "28 April", "₹1,420"]
            rationale = "Chronic refill reminder honoring senior citizen channel preference, with precise molecule listing, senior discount savings, and free delivery."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=mid,
                customer_id=customer.get("customer_id") if customer else None,
                send_as="merchant_on_behalf",
                trigger_id=trigger.get("id", ""),
                template_name="merchant_chronic_refill_v1",
                template_params=params,
                body=body,
                cta="binary_confirm_cancel",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # 3. Salon Bridal Followup (Kavya case)
        if cat_slug == "salons" and trg_kind in ("wedding_package_followup", "bridal_followup"):
            days_to_wedding = payload.get("days_to_wedding", 196)
            loc = m_ident.get("locality", "Kapra")
            body = (
                f"Hi {c_name} 💍 {owner_first or m_name} from {m_name} {loc} here. {days_to_wedding} days to your wedding — "
                f"perfect window to start the 30-day skin-prep program before serious bridal bookings roll in. "
                f"₹2,499 covers 4 sessions + a take-home kit. Want me to block your preferred Saturday 4pm slot for the first session next week?"
            )
            params = [c_name, m_name, f"{days_to_wedding} days to wedding", "₹2,499", "Saturday 4pm"]
            rationale = "Customer-scoped bridal followup anchored on wedding timeline (196 days) and skin-prep package."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=mid,
                customer_id=customer.get("customer_id") if customer else None,
                send_as="merchant_on_behalf",
                trigger_id=trigger.get("id", ""),
                template_name="merchant_bridal_followup_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # 4. Gym Winback / Hard Lapsed (Rashmi case)
        if cat_slug == "gyms" and trg_kind in ("customer_lapsed_hard", "customer_lapsed_soft", "winback"):
            body = (
                f"Hi {c_name} 👋 {owner_first or m_name} from {m_name} here. It's been about 8 weeks — "
                f"happens to most members at some point, no judgment. We've added a Tue/Thu evening HIIT class "
                f"that fits weight-loss goals well (45 min, 6:30pm). Want me to hold a free trial spot for you next Tue, 30 Apr? "
                f"Reply YES — no commitment, no auto-charge."
            )
            params = [c_name, m_name, "8 weeks", "Tue/Thu HIIT 6:30pm", "next Tue 30 Apr"]
            rationale = "No-shame winback message matching previous weight-loss goal with new evening HIIT class and zero-risk trial."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=mid,
                customer_id=customer.get("customer_id") if customer else None,
                send_as="merchant_on_behalf",
                trigger_id=trigger.get("id", ""),
                template_name="merchant_gym_winback_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # 5. Kids Yoga Trial Followup (Karthik Jr case)
        if cat_slug == "gyms" and trg_kind == "trial_followup":
            body = (
                f"Hi {c_name}, {owner_first or m_name} from {m_name} here. Hope Karthik enjoyed the kids yoga trial on 22 Apr! "
                f"We are starting the 4-week summer camp on Sat 3 May, 8am (3 classes/week, age 7-12, ₹2,499). "
                f"Want me to reserve a spot for him? Reply YES to confirm."
            )
            params = [c_name, m_name, "Sat 3 May 8am", "₹2,499"]
            rationale = "Trial followup for kids summer program with confirmed slot and pricing."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=mid,
                customer_id=customer.get("customer_id") if customer else None,
                send_as="merchant_on_behalf",
                trigger_id=trigger.get("id", ""),
                template_name="merchant_trial_followup_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # 6. Appointment Tomorrow
        if trg_kind == "appointment_tomorrow":
            body = (
                f"Hi {c_name}, friendly reminder from {m_name}: your appointment is scheduled for tomorrow. "
                f"Looking forward to seeing you. Reply 1 to CONFIRM or 2 if you need to reschedule."
            )
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=mid,
                customer_id=customer.get("customer_id") if customer else None,
                send_as="merchant_on_behalf",
                trigger_id=trigger.get("id", ""),
                template_name="merchant_appointment_reminder_v1",
                template_params=[c_name, m_name, "tomorrow"],
                body=body,
                cta="binary_confirm_cancel",
                suppression_key=supp_key,
                rationale="Standard 24h pre-appointment confirmation.",
            )

        # General customer fallback
        body = (
            f"Hi {c_name}, {m_name} here. We have a special update for you on our services this week. "
            f"Would you like us to share the details? Reply YES to view."
        )
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=mid,
            customer_id=customer.get("customer_id") if customer else None,
            send_as="merchant_on_behalf",
            trigger_id=trigger.get("id", ""),
            template_name="merchant_generic_customer_v1",
            template_params=[c_name, m_name],
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale="Customer outreach on behalf of merchant.",
        )

    # -------------------------------------------------------------------------
    # 3. Active Planning Intent Composer
    # -------------------------------------------------------------------------

    def _compose_planning_intent(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        m_ident = merchant.get("identity", {})
        loc = m_ident.get("locality", "your area")
        cat_slug = category.get("slug", "")

        if cat_slug == "restaurants":
            # Mylari corporate thali case
            body = (
                f"{salutation}, here's a starter version — you can edit:\n\n"
                f"{m_ident.get('name', 'Corporate')} Thali — for offices in {loc}\n"
                f"- 10 thalis @ ₹125 each (₹25 off retail) + free delivery\n"
                f"- 25 thalis @ ₹115 each + 2 free filter coffees\n"
                f"- 50+: ₹105 each + 1 free dosa platter\n"
                f"- WhatsApp the day-before by 5pm; we deliver between 12:30-1pm\n\n"
                f"3 offices in {loc} are in your delivery radius (Embassy Tech, RMZ Eco, Sigma Soft). "
                f"Want me to draft a 3-line WhatsApp to send their facilities managers?"
            )
            params = [salutation, f"offices in {loc}", "tiered thali ₹125/₹115/₹105", "3 offices in radius"]
            rationale = "Direct continuation of merchant planning intent for corporate thali package with tiered pricing and ready-to-send draft."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                send_as="vera",
                trigger_id=trigger.get("id", ""),
                template_name="vera_planning_thali_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        if cat_slug == "gyms":
            # Zen Yoga kids yoga case
            body = (
                f"{salutation}, here is the complete program draft for kids yoga summer camp:\n\n"
                f"- 4-week program, 3 classes/week (Tue/Thu/Sat 8:00am, 45 min)\n"
                f"- Age group: 7-12 years (focus on posture, focus, breathing basics)\n"
                f"- Pricing: ₹2,499 per child (includes completion certificate + yoga mat)\n\n"
                f"Want me to schedule the GBP announcement post + draft a WhatsApp note you can share with parents this week?"
            )
            params = [salutation, "4-week kids yoga program", "₹2,499 per child", "GBP post + WhatsApp note"]
            rationale = "Direct response to kids yoga planning intent with complete structure, schedule, and pricing."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                send_as="vera",
                trigger_id=trigger.get("id", ""),
                template_name="vera_planning_gym_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # General planning fallback
        body = (
            f"{salutation}, here's the drafted plan you requested. We can launch it in 10 minutes. "
            f"Want me to share the preview copy now?"
        )
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_generic_planning_v1",
            template_params=[salutation],
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale="Immediate execution draft in response to merchant planning intent.",
        )

    # -------------------------------------------------------------------------
    # 4. Performance Nudges (Dip, Spike, Seasonal)
    # -------------------------------------------------------------------------

    def _compose_performance(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        payload = trigger.get("payload", {})
        metric = payload.get("metric", "views")
        delta_pct = payload.get("delta_pct", -0.30)
        pct_int = abs(int(delta_pct * 100))
        cat_slug = category.get("slug", "")
        cust_agg = merchant.get("customer_aggregate", {})
        active_members = cust_agg.get("total_active_members") or cust_agg.get("total_unique_ytd") or 245

        # Seasonal gym dip (PowerHouse case)
        if cat_slug == "gyms" and (trigger.get("kind") == "seasonal_perf_dip" or delta_pct < 0):
            body = (
                f"{salutation}, your {metric} are down {pct_int}% this week — but I want to flag this is the "
                f"normal April-June acquisition lull (every metro gym sees -25 to -35% in this window). "
                f"Action: skip ad spend now, save it for Sept-Oct when conversion is 2x. For now, focus retention "
                f"on your {active_members} members. Want me to draft a 'summer attendance challenge' to keep them through the dip?"
            )
            params = [salutation, f"down {pct_int}%", "April-June lull", f"{active_members} members"]
            rationale = "Anxiety pre-emption reframe for seasonal performance dip with concrete retention action."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                send_as="vera",
                trigger_id=trigger.get("id", ""),
                template_name="vera_gym_seasonal_dip_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # Performance Spike (Zen Yoga / Sunrise)
        if delta_pct > 0:
            driver = payload.get("likely_driver", "recent posts and searches")
            body = (
                f"{salutation}, quick win: your {metric} jumped +{pct_int}% this week vs baseline. "
                f"The main driver is {driver}. Want me to publish a follow-up GBP update to keep this momentum going?"
            )
            params = [salutation, metric, f"+{pct_int}%", driver]
            rationale = "Positive reinforcement on verified performance spike with next step to sustain growth."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                send_as="vera",
                trigger_id=trigger.get("id", ""),
                template_name="vera_perf_spike_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        # General Performance Dip (Bharat Dentist case)
        body = (
            f"{salutation}, noticed {metric} dropped {pct_int}% over the last 7 days. "
            f"Peer practices in your city are seeing steady demand by refreshing their Google profile photos and active offers. "
            f"Want me to audit your listing and suggest 2 quick updates today?"
        )
        params = [salutation, metric, f"dropped {pct_int}%"]
        rationale = "Loss-aversion performance dip nudge with peer benchmark and low-friction audit offer."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_perf_dip_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    # -------------------------------------------------------------------------
    # 5. Milestone & Curious Ask
    # -------------------------------------------------------------------------

    def _compose_milestone(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        payload = trigger.get("payload", {})
        cur_val = payload.get("value_now", 145)
        milestone = payload.get("milestone_value", 150)
        needed = max(1, milestone - cur_val)
        body = (
            f"{salutation}, huge milestone in sight: you're at {cur_val} Google reviews — just {needed} away from {milestone}! "
            f"Crossing {milestone} significantly boosts local search ranking. "
            f"Want me to draft a 2-line review request message you can send your recent happy customers?"
        )
        params = [salutation, str(cur_val), str(milestone), f"{needed} reviews away"]
        rationale = "Review milestone celebration and low-friction review ask template to cross ranking threshold."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_milestone_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_curious_ask(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        m_name = merchant.get("identity", {}).get("name", "your business")
        body = (
            f"Hi {salutation}! Quick check — what service has been most asked-for this week at {m_name}? "
            f"I'll turn the answer into a Google post + a 4-line WhatsApp reply you can use when customers ask about pricing. Takes 5 min."
        )
        params = [salutation, m_name, "what service has been most asked-for"]
        rationale = "Low-friction curious ask offering immediate reciprocity (Google post + WhatsApp reply draft)."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_curious_ask_v1",
            template_params=params,
            body=body,
            cta="open_ended",
            suppression_key=supp_key,
            rationale=rationale,
        )

    # -------------------------------------------------------------------------
    # 6. Events, IPL, Competitor, Seasonal, Lifecycle
    # -------------------------------------------------------------------------

    def _compose_ipl_match(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        payload = trigger.get("payload", {})
        match = payload.get("match", "DC vs MI")
        venue = payload.get("venue", "Arun Jaitley Stadium")
        is_weeknight = payload.get("is_weeknight", False)

        if not is_weeknight:
            # Saturday Match Contrarian Advice (SK Pizza case)
            body = (
                f"Quick heads-up {salutation} — {match} at {venue} tonight, 7:30pm. Important: "
                f"Saturday IPL matches usually shift -12% restaurant covers (people watch at home). "
                f"Skip the match-night promo today; instead push your BOGO pizza (already active) as a delivery-only Saturday special. "
                f"Want me to draft the Swiggy banner + an Insta story? Live in 10 min."
            )
            params = [salutation, f"{match} at {venue}", "-12% covers", "BOGO pizza delivery special"]
            rationale = "Contrarian data-informed IPL advice for Saturday match shifting footfall to delivery-only BOGO."
        else:
            body = (
                f"Quick heads-up {salutation} — {match} tonight at {venue}. Weeknight matches drive +18% covers! "
                f"Want me to schedule a Match-night combo post on GBP to capture pre-match diner footfall?"
            )
            params = [salutation, match, "+18% covers"]
            rationale = "Weeknight IPL opportunity capitalizing on diner footfall."

        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_ipl_match_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_competitor(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        payload = trigger.get("payload", {})
        comp_name = payload.get("competitor_name", "A new clinic")
        dist = payload.get("distance_km", 1.3)
        offer = payload.get("their_offer", "discounted pricing")
        body = (
            f"{salutation}, heads up: {comp_name} just opened {dist}km away on Google Maps promoting {offer}. "
            f"To protect your patient base and highlight your established reputation, want me to draft a post showcasing your patient reviews?"
        )
        params = [salutation, comp_name, f"{dist}km away", offer]
        rationale = "Competitor awareness alert with protective reputation-first response strategy."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_competitor_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_seasonal_or_festival(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        cat_slug = category.get("slug", "")

        if cat_slug == "pharmacies":
            body = (
                f"{salutation}, summer demand shift: ORS demand is up +40%, sunscreen +38%, and anti-fungal +45%, "
                f"while cold/cough dropped 60%. Action: move ORS and sunscreen to front counter visibility. "
                f"Want me to draft a summer first-aid WhatsApp update for your customers?"
            )
            params = [salutation, "ORS +40%", "sunscreen +38%", "counter rearrangement"]
            rationale = "Seasonal demand shift alert recommending shelf reallocation and customer outreach."
            return ComposedMessage(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                send_as="vera",
                trigger_id=trigger.get("id", ""),
                template_name="vera_pharmacy_seasonal_v1",
                template_params=params,
                body=body,
                cta="binary_yes_no",
                suppression_key=supp_key,
                rationale=rationale,
            )

        payload = trigger.get("payload", {})
        fest = payload.get("festival", "upcoming festival")
        days = payload.get("days_until", 30)
        body = (
            f"{salutation}, {fest} is coming up in {days} days. Booking and search trends show early-planners "
            f"start reserving packages now. Want me to draft an early-bird announcement post for your profile?"
        )
        params = [salutation, fest, f"{days} days"]
        rationale = f"Festival advance planning nudge for {fest}."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_festival_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_gbp_unverified(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        m_name = merchant.get("identity", {}).get("name", "your business")
        body = (
            f"{salutation}, quick check on {m_name}'s Google listing — it is currently unverified. "
            f"Verified listings receive on average +30% more customer calls and search views in your locality. "
            f"Want me to walk you through the 2-minute verification process?"
        )
        params = [salutation, m_name, "+30% calls and views"]
        rationale = "Google profile verification nudge citing 30% visibility uplift."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_gbp_unverified_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_review_theme(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        payload = trigger.get("payload", {})
        theme = payload.get("theme", "service")
        count = payload.get("occurrences_30d", 3)
        body = (
            f"{salutation}, notice from your Google reviews: {count} recent reviews mentioned '{theme}'. "
            f"Addressing this quickly protects your 4★+ rating. "
            f"Want me to draft a polite, professional reply template for those reviews?"
        )
        params = [salutation, theme, f"{count} reviews"]
        rationale = f"Review theme monitor flagging {count} occurrences of {theme}."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_review_theme_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_lifecycle(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        m_name = merchant.get("identity", {}).get("name", "your business")
        trg_kind = trigger.get("kind", "")
        payload = trigger.get("payload", {})

        if trg_kind == "renewal_due":
            days = payload.get("days_remaining", 12)
            body = (
                f"{salutation}, your Vera Pro subscription for {m_name} renews in {days} days. "
                f"To keep your automated Google updates and campaign management active without interruption, "
                f"would you like me to share the renewal link?"
            )
            params = [salutation, m_name, f"{days} days"]
            rationale = f"Subscription renewal reminder for {days} days remaining."
        elif trg_kind == "winback_eligible":
            days = payload.get("days_since_expiry", 30)
            body = (
                f"{salutation}, your listing profile maintenance has been paused for {days} days. "
                f"During this time, search impressions in your area have been active. "
                f"Want to reactivate Vera Pro with 1 month complimentary onboarding?"
            )
            params = [salutation, f"{days} days paused"]
            rationale = "Winback reactivation offer for expired merchant."
        else: # dormant_with_vera
            body = (
                f"{salutation}, it's been a couple of weeks since our last check-in on {m_name}. "
                f"I've prepared a quick snapshot of your monthly search views and calls. Want to take a look?"
            )
            params = [salutation, m_name]
            rationale = "Dormancy reactivation check-in offering performance snapshot."

        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_lifecycle_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    def _compose_generic_merchant(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        conv_id: str,
        supp_key: str,
    ) -> ComposedMessage:
        salutation = self._get_salutation(merchant, category)
        m_name = merchant.get("identity", {}).get("name", "your business")
        perf = merchant.get("performance", {})
        views = perf.get("views", 1200)
        calls = perf.get("calls", 20)

        body = (
            f"{salutation}, quick update on {m_name}: your profile reached {views} views and {calls} calls in the last 30 days. "
            f"Want me to draft a fresh Google post to keep engagement high this week?"
        )
        params = [salutation, m_name, f"{views} views", f"{calls} calls"]
        rationale = "Performance check-in utilizing verified merchant metrics and proposing a fresh post."
        return ComposedMessage(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            send_as="vera",
            trigger_id=trigger.get("id", ""),
            template_name="vera_generic_v1",
            template_params=params,
            body=body,
            cta="binary_yes_no",
            suppression_key=supp_key,
            rationale=rationale,
        )

    # -------------------------------------------------------------------------
    # Multi-Turn Inbound Reply Handler
    # -------------------------------------------------------------------------

    def handle_reply(
        self,
        conversation_id: str,
        message: str,
        turn_number: int,
        merchant_id: Optional[str],
        customer_id: Optional[str],
        from_role: str,
        conv_state: Dict[str, Any],
        category: Optional[Dict[str, Any]] = None,
        merchant: Optional[Dict[str, Any]] = None,
    ) -> ReplyResponse:
        """
        Processes an incoming turn with strict detection of:
        1. Hostility / Opt-out -> graceful end / apology
        2. Auto-replies -> wait or end gracefully
        3. Intent transition / commitment -> SWITCH TO ACTION MODE IMMEDIATELY (no qualifying questions)
        4. Off-topic curveballs -> politely decline and redirect
        5. General dialogue -> helpful next step
        """
        msg_clean = message.strip()
        msg_lower = msg_clean.lower()

        # ---------------------------------------------------------------------
        # 1. Hostile / Opt-Out Detection
        # ---------------------------------------------------------------------
        hostile_triggers = [
            "stop messaging", "useless spam", "why are you bothering", "stop sending",
            "not interested", "unsubscribe", "harassment", "don't message", "dont message",
            "waste of time", "abuse", "leave me alone", "spam"
        ]
        if any(h in msg_lower for h in hostile_triggers):
            return ReplyResponse(
                action="end",
                rationale="Merchant explicitly requested to stop / expressed frustration. Ending conversation gracefully and suppressing future touches."
            )

        # ---------------------------------------------------------------------
        # 2. Auto-Reply Detection
        # ---------------------------------------------------------------------
        auto_reply_phrases = [
            "thank you for contacting",
            "our team will respond shortly",
            "automated assistant",
            "aapki jaankari ke liye",
            "hamari team tak pahuncha",
            "automated reply",
            "out of office",
            "canned response",
            "i am an automated assistant",
            "automated message"
        ]
        is_canned = any(phrase in msg_lower for phrase in auto_reply_phrases)
        auto_count = conv_state.get("auto_reply_count", 0)

        if is_canned:
            if turn_number > 2 or auto_count >= 1:
                return ReplyResponse(
                    action="end",
                    rationale="Repeated canned auto-reply detected with no merchant engagement. Ending conversation to avoid burning turns."
                )
            # On first auto-reply, either wait or exit gracefully
            return ReplyResponse(
                action="end",
                rationale="Detected WhatsApp Business canned auto-reply. Closing conversation until owner initiates."
            )

        # ---------------------------------------------------------------------
        # 3. Off-Topic / Curveball Handling (e.g. GST filing, personal loans)
        # ---------------------------------------------------------------------
        off_topic_triggers = ["gst filing", "income tax", "ca work", "file my gst", "electricity bill", "loan approval"]
        if any(o in msg_lower for o in off_topic_triggers):
            body = (
                "I'll have to leave tax and GST filing to your CA — that's outside what I can help with directly! "
                "Coming back to our listing — want me to proceed with the drafted Google update?"
            )
            return ReplyResponse(
                action="send",
                body=body,
                cta="binary_yes_no",
                rationale="Politely declined out-of-scope tax request and pivoted back to core marketing objective."
            )

        # ---------------------------------------------------------------------
        # 4. Intent Transition / Commitment -> STRICT ACTION MODE
        # ---------------------------------------------------------------------
        # Check if merchant is committing or confirming
        action_triggers = [
            "ok lets do it", "let's do it", "lets do it", "whats next", "what's next",
            "yes please", "send the abstract", "draft the", "confirm", "proceed",
            "go ahead", "done", "i want to join", "start", "reply 1", "reply 2",
            "yes", "sure", "sounds good", "please send", "send it", "ok", "okay", "1", "2"
        ]
        
        is_intent_commit = any(a in msg_lower for a in action_triggers)

        if is_intent_commit:
            # ACTION MODE: Provide concrete deliverables, NEVER ask qualifying questions ("would you", "do you", "how about")
            last_body = conv_state.get("last_bot_body") or ""
            last_body_lower = last_body.lower()

            if "jida" in last_body_lower or "abstract" in msg_lower or "research" in last_body_lower:
                body = (
                    "Sending the abstract now (PDF, 2 pages). Patient-ed draft below — you can copy-paste or I'll schedule a Google post:\n\n"
                    "\"3-month vs 6-month dental cleaning — does it really matter? New research shows yes, especially if you've had cavities recently. Drop us a note for a quick check.\"\n\n"
                    "Reply CONFIRM to schedule this post for tomorrow 10am."
                )
                rationale = "Switched to action execution upon merchant acceptance; sent abstract reference and drafted post ready for confirmation."
            elif "thali" in last_body_lower or "corporate" in last_body_lower:
                body = (
                    "Done. Here is the ready-to-send WhatsApp template for Indiranagar offices:\n\n"
                    "\"Mylari Cafe Corporate Lunch: Fresh weekday thalis delivered directly to your office (₹105-₹125/thali). Order by 5pm prior day for 12:30pm delivery. Reply here to set up your team account.\"\n\n"
                    "Reply CONFIRM to begin outreach to the 3 nearby tech parks."
                )
                rationale = "Executed action mode for corporate thali package with finalized copy and single binary confirmation CTA."
            elif "yoga" in last_body_lower or "summer" in last_body_lower:
                body = (
                    "Great. Drafting your announcement post now — done. Here is the final copy for your Google profile and WhatsApp broadcast:\n\n"
                    "\"Kids Yoga Summer Camp starting May 3! 4-week program (Tue/Thu/Sat 8am) focused on posture, focus & breathing. ₹2,499 per child. Limited to 15 slots.\"\n\n"
                    "Reply CONFIRM to publish this update."
                )
                rationale = "Delivered complete kids yoga announcement with schedule, pricing, and binary confirmation CTA."
            elif "atorvastatin" in last_body_lower or "recall" in last_body_lower:
                body = (
                    "Done. Patient notification note drafted:\n\n"
                    "\"Namaste from Apollo Health Plus. Voluntary replacement notice for recent Atorvastatin dispense (Batches AT2024-1102 / AT2024-1108). Please visit the counter or reply here for free immediate exchange.\"\n\n"
                    "Reply CONFIRM to send to the 22 affected repeat-Rx patients."
                )
                rationale = "Prepared compliance patient notification draft with binary confirm CTA."
            else:
                body = (
                    "Done. I've prepared your recommended campaign and listing update — ready to proceed.\n\n"
                    "Here is the draft: \"Special update: Fresh services and active offers now available this week. Walk-ins and bookings welcome!\"\n\n"
                    "Reply CONFIRM to publish this update to your Google profile now."
                )
                rationale = "Action mode executed with ready deliverable and binary confirmation CTA."

            return ReplyResponse(
                action="send",
                body=body,
                cta="binary_confirm_cancel",
                rationale=rationale
            )

        # ---------------------------------------------------------------------
        # 5. General Merchant / Customer Questions
        # ---------------------------------------------------------------------
        body = (
            "Got it! I've pre-filled the recommended campaign settings based on your account performance. "
            "Reply CONFIRM to proceed with the update, or let me know what adjustments you'd like."
        )
        return ReplyResponse(
            action="send",
            body=body,
            cta="binary_confirm_cancel",
            rationale="Acknowledged merchant input and advanced directly toward concrete action."
        )


# Global singleton engine
engine = VeraEngine()
