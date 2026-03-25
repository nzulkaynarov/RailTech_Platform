# Design Doc: Domain-Driven Architecture (DDD) for RailTech B2B Ecosystem

**Date:** 2026-03-10
**Status:** Approved by User
**Context:** The platform is transitioning from a strictly "Railway & Machinery" focus to a universal B2B e-commerce platform that handles railway equipment, general industrial goods (paint, hardware), and services (logistics, repair) under one unified system.

## 1. Core Architecture Changes

The monolithic requirement that "all products must link to a LocomotiveGroup" has been replaced with a **Domain-Driven Taxonomy**. 

The system now categorizes all offerings into three distinct `Domain` types:
1.  **RAILWAY_MACHINERY (ЖД и Спецтехника):**
    *   **Rules:** Strict hierarchical binding. Products MUST be linked to an `EquipmentGroup` (Type → Series). 
    *   **Use Case:** Engines, wheelsets, specific block systems.
2.  **GENERAL_GOODS (Общие промышленные товары):**
    *   **Rules:** Flat catalog with dynamic `JSONB` parameters. No equipment linkage required or enforced.
    *   **Use Case:** Paint, hardware, construction materials.
3.  **SERVICES (Услуги):**
    *   **Rules:** Non-physical entities. Calculated by variables (UOM) like hours, trips, or km. No customs/logistics overhead in Landed Cost calculations.
    *   **Use Case:** Logistics tracking, repair services.

## 2. Updated Components & Logic

### 2.1. ER Database Schema

*   **`Product` Model:**
    *   Added `domain_type` (Enum).
    *   `equipment_groups` (M2M) is now only mandatory if `domain_type == RAILWAY_MACHINERY`.
    *   `specifications` (JSONB) is used heavily for GENERAL_GOODS.
*   **`EquipmentGroup` Model:** (Renamed from `LocomotiveGroup` for broader applicability). Fits Locomotives, Wagons, and Heavy Machinery.

### 2.2. Domain-Aware Smart Match (Excel Parsing)

The Excel parsing script now acts as a **Domain Router**:
*   Instead of just looking up `gost_drawing`, the algorithm evaluates the item name and keywords to route it to the correct domain.
*   "Электродвигатель ВЛ80" -> `RAILWAY_MACHINERY`.
*   "Краска ПФ-115 20кг" -> `GENERAL_GOODS`.
*   "Доставка фурой до депо" -> `SERVICES`.

### 2.3. Finance & Landed Cost (CRM)

The `Quote Builder` handles services differently than physical goods:
*   Physical Goods (RAILWAY, GOODS) require calculating DAP (Logistics + Customs) on top of FCA.
*   Services (SERVICES) do not incur DAP overhead in the same way, bypassing customs logic.

## 3. UI/UX Adjustments

*   **Public Catalog (`b2b.railtech.uz`):** The faceted sidebar adapts. If a user selects the "Railway" domain, strict filters (Type/Series) appear. If they select "General Goods", standard category filters appear.
*   **Client Dashboard (`cabinet.railtech.uz`):** 70/30 split view for deals groups items visually by their Domain (Equipment vs Consumables vs Services).

## 4. Next Steps
- Transition to `writing-plans` skill to formulate the exact Django/React implementation plan based on these new constraints.
