"""Plain-language help for every setting key, shown under the setting in the app and given to the AI assistant/MCP.

key -> (help_en, help_ar, caution_en | None, caution_ar | None). Shared by all drivers (keys are driver-neutral).
"""
from __future__ import annotations

SETTING_HELP: dict[str, tuple[str, str, str | None, str | None]] = {
    "output_priority": (
        "Which source feeds the house first. Utility-Solar-Battery: the grid powers the house whenever it is there, so the "
        "battery charges during grid hours. Solar-Utility-Battery: solar first, then grid. Solar-Battery-Utility: solar and "
        "battery first, grid only when the battery is low.",
        "من أين يأخذ البيت الكهرباء أولاً. «شبكة ثم شمس ثم بطارية»: البيت على الكهرباء وقت وجودها فتشحن البطارية في "
        "ساعات الكهرباء. «شمس ثم شبكة ثم بطارية»: الألواح أولاً ثم الكهرباء. «شمس ثم بطارية ثم شبكة»: الألواح والبطارية "
        "أولاً، والكهرباء فقط عندما تنخفض البطارية.",
        "With short or rare grid hours, Solar-Battery-Utility can leave the battery uncharged when the grid comes back.",
        "إن كانت الكهرباء قليلة، فخيار «شمس ثم بطارية ثم شبكة» قد يضيّع ساعات الكهرباء دون أن تشحن البطارية."),
    "charger_priority": (
        "What may charge the battery. Solar first: the grid charges only when there is no solar. Solar + Utility: both "
        "charge together (fastest). Only solar: the grid never charges the battery.",
        "من يشحن البطارية. «الشمس أولاً»: الكهرباء تشحن فقط عند غياب الشمس. «شمس + كهرباء»: الاثنان معاً وهو الأسرع. "
        "«الشمس فقط»: الكهرباء لا تشحن البطارية أبداً.",
        None, None),
    "max_ac_charge_current": (
        "Highest current the grid may push into the battery. Higher charges faster during grid hours and draws more from "
        "the grid. A common choice is 0.2-0.3 of the battery capacity (200 Ah -> 40-60 A).",
        "أقصى تيار تشحن به الكهرباء البطارية. الأعلى يشحن أسرع في ساعات الكهرباء ويسحب أكثر من الشبكة. "
        "المعتاد 0.2 إلى 0.3 من سعة البطارية (بطارية 200 أمبير ساعة ← 40 إلى 60 أمبير).",
        "Never above the battery BMS maximum charge current, and make sure the house breaker can carry the extra load.",
        "لا تتجاوز أقصى تيار شحن يقبله BMS البطارية، وتأكد أن قاطع البيت يتحمّل السحب الإضافي."),
    "max_charge_current": (
        "Highest total charging current from solar and grid together.",
        "أقصى تيار شحن إجمالي من الألواح والكهرباء معاً.",
        "Keep it at or below the battery BMS maximum (usually 0.5 of capacity: 200 Ah -> 100 A).",
        "لا تتجاوز حد BMS البطارية (عادة نصف السعة: 200 أمبير ساعة ← 100 أمبير)."),
    "buzzer": (
        "The inverter's beeper for alarms and events.",
        "صافرة الإنفرتر للتنبيهات والأحداث.",
        "Turning it off also silences fault and overload alarms.",
        "إطفاؤها يُسكت أيضاً إنذارات الأعطال والحمل الزائد."),
    "primary_source_beep": (
        "Beep when the grid (primary source) cuts out. Many people turn it off when outages are frequent at night.",
        "صوت عند انقطاع الكهرباء. كثيرون يطفئونه إن كان الانقطاع متكرراً في الليل.",
        None, None),
    "ac_input_range": (
        "Appliance accepts a wide grid voltage range, which suits weak or unstable grids. UPS accepts a narrow range and "
        "switches faster, for sensitive computers.",
        "«أجهزة منزلية» يقبل مدى واسعاً من جهد الكهرباء ويناسب الكهرباء الضعيفة أو المتذبذبة. «UPS» يقبل مدى ضيقاً "
        "ويتحوّل أسرع، للحواسيب الحساسة.",
        "On a weak grid, UPS may reject low grid voltage and keep the house on the battery.",
        "مع كهرباء ضعيفة، وضع UPS قد يرفض الجهد المنخفض فيبقى البيت على البطارية."),
    "overload_restart": (
        "Restart the output by itself after an overload shut it down. Usually best left on.",
        "يعيد تشغيل الخرج تلقائياً بعد أن يطفئه حمل زائد. الأفضل غالباً تركه مفعّلاً.",
        "If overloads keep happening, reduce the load instead.",
        "إن تكرر الحمل الزائد فخفّف الأحمال بدل الاعتماد عليه."),
    "overtemp_restart": (
        "Restart by itself once the inverter has cooled down after overheating. Usually best left on.",
        "يعيد التشغيل تلقائياً بعد أن يبرد الإنفرتر من ارتفاع الحرارة. الأفضل غالباً تركه مفعّلاً.",
        "If it overheats often, check ventilation around the inverter.",
        "إن تكرر ارتفاع الحرارة فافحص التهوية حول الإنفرتر."),
    "power_saving": (
        "When the load is tiny (about 25-50 W) the inverter switches its output off and checks for load every few seconds. "
        "Only useful in places that stand empty for long periods.",
        "عندما يكون الحمل صغيراً جداً (25 إلى 50 واط تقريباً) يطفئ الإنفرتر الخرج ويفحص كل بضع ثوانٍ. مفيد فقط في "
        "الأماكن الفارغة لفترات طويلة.",
        "Small devices (router, cameras, LED lights, chargers) may switch off. Keep it off in a lived-in home.",
        "قد تنطفئ الأجهزة الصغيرة (الراوتر، الكاميرات، الإنارة، الشواحن). اتركه مطفأً في البيت المسكون."),
    "backlight": (
        "Keep the inverter screen lit.",
        "إبقاء إضاءة شاشة الإنفرتر.",
        None, None),
    "lcd_auto_return": (
        "The inverter screen goes back to the main page after about a minute.",
        "شاشة الإنفرتر تعود للصفحة الرئيسية بعد دقيقة تقريباً.",
        None, None),
    "battery_recharge_soc": (
        "When the battery falls to this level, the house moves to the grid (if it is there).",
        "عندما تنخفض البطارية إلى هذه النسبة ينتقل البيت إلى الكهرباء (إن وُجدت).",
        None, None),
    "battery_redischarge_soc": (
        "When the battery is charged back to this level, the house returns to the battery. Keep it well above the "
        "back-to-grid level.",
        "عندما تشحن البطارية إلى هذه النسبة يرجع البيت إلى البطارية. اجعلها أعلى بوضوح من نسبة العودة للشبكة.",
        None, None),
    "battery_cutoff_soc": (
        "With no grid, the inverter stops using the battery at this level to protect it. 10-20% is common for lithium.",
        "عند غياب الكهرباء يوقف الإنفرتر سحب البطارية عند هذه النسبة لحمايتها. المعتاد لليثيوم 10 إلى 20%.",
        "Lower values give more runtime but wear the battery faster.",
        "النسبة الأقل تعطي وقتاً أطول لكنها تُتعب البطارية أسرع."),
    "ac2_off_soc": (
        "The second output (AC2) switches off when the battery falls to this level, saving the battery for the essentials. "
        "Put non-essential loads (water heater, pump) on AC2.",
        "المخرج الثاني (AC2) ينطفئ عندما تنخفض البطارية إلى هذه النسبة، فتبقى البطارية للأساسيات. "
        "صِل الأحمال غير الضرورية (السخان، المضخة) على AC2.",
        None, None),
    "ac2_on_soc": (
        "The second output (AC2) switches back on when the battery is charged to this level.",
        "المخرج الثاني (AC2) يعود للعمل عندما تشحن البطارية إلى هذه النسبة.",
        None, None),
    "battery_cutoff_voltage": (
        "With no grid, the inverter stops using the battery at this voltage to protect it.",
        "عند غياب الكهرباء يوقف الإنفرتر سحب البطارية عند هذا الجهد لحمايتها.",
        "Follow the battery maker's datasheet.", "التزم بورقة مواصفات البطارية."),
    "bulk_charge_voltage": (
        "Voltage the charger pushes the battery up to.",
        "الجهد الذي يرفع إليه الشاحن البطارية.",
        "A wrong value can damage the battery. Follow the battery maker's datasheet.",
        "القيمة الخاطئة قد تتلف البطارية. التزم بورقة مواصفات البطارية."),
    "float_charge_voltage": (
        "Voltage that holds a full battery topped up.",
        "الجهد الذي يحافظ على البطارية ممتلئة.",
        "A wrong value can damage the battery. Follow the battery maker's datasheet.",
        "القيمة الخاطئة قد تتلف البطارية. التزم بورقة مواصفات البطارية."),
    "battery_recharge_voltage": (
        "When the battery falls to this voltage, the house moves to the grid (if it is there).",
        "عندما ينخفض جهد البطارية إلى هذه القيمة ينتقل البيت إلى الكهرباء (إن وُجدت).",
        None, None),
    "battery_redischarge_voltage": (
        "When the battery is charged back to this voltage, the house returns to the battery.",
        "عندما يرتفع جهد البطارية إلى هذه القيمة يرجع البيت إلى البطارية.",
        None, None),
}


def help_for(key: str) -> dict[str, str | None]:
    h = SETTING_HELP.get(key)
    if not h:
        return {"help": None, "help_ar": None, "caution": None, "caution_ar": None}
    return {"help": h[0], "help_ar": h[1], "caution": h[2], "caution_ar": h[3]}
