"""The challenge windows.

Built on NSAlert with accessory views rather than raw NSWindow: NSAlert brings
its own modal loop and button handling, which is a lot less to get wrong.

Autocorrect and smart substitution are switched OFF in the typing view. macOS
would otherwise "helpfully" rewrite Melville's vocabulary as you type, which
turns a transcription exercise into a fight with the spell checker.
"""

from __future__ import annotations

from AppKit import (
    NSAlert, NSAlertFirstButtonReturn, NSBezelBorder, NSColor, NSFont,
    NSMakeRect, NSScrollView, NSTextField, NSTextView, NSView, NSViewWidthSizable,
)

from friction.challenges import core as C

W = 560


def _scrolling_text(rect, *, editable: bool, font, text: str = ""):
    scroll = NSScrollView.alloc().initWithFrame_(rect)
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(NSBezelBorder)
    scroll.setAutoresizingMask_(NSViewWidthSizable)

    tv = NSTextView.alloc().initWithFrame_(scroll.contentView().bounds())
    tv.setAutoresizingMask_(NSViewWidthSizable)
    tv.setVerticallyResizable_(True)
    tv.setHorizontallyResizable_(False)
    tv.textContainer().setWidthTracksTextView_(True)
    tv.setFont_(font)
    tv.setEditable_(editable)
    tv.setString_(text)
    if editable:
        # The whole point is that you type it. Don't let macOS type it for you.
        tv.setAutomaticQuoteSubstitutionEnabled_(False)
        tv.setAutomaticDashSubstitutionEnabled_(False)
        tv.setAutomaticTextReplacementEnabled_(False)
        tv.setAutomaticSpellingCorrectionEnabled_(False)
        tv.setContinuousSpellCheckingEnabled_(False)
    else:
        tv.setBackgroundColor_(NSColor.controlBackgroundColor())
        tv.setTextColor_(NSColor.secondaryLabelColor())
    scroll.setDocumentView_(tv)
    return scroll, tv


def _label(rect, text, *, size=11, secondary=True):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.systemFontOfSize_(size))
    if secondary:
        f.setTextColor_(NSColor.secondaryLabelColor())
    return f


# --- step 1, every tier: are you sure? -------------------------------------

TIMED, UNTIMED, CANCELLED = "timed", "untimed", None


def confirm_unlock(target: str, plan, next_step: str | None) -> str | None:
    """The "are you sure?" every tier gets before its extra friction.

    Returns TIMED, UNTIMED, or CANCELLED. When the plan offers a choice, the
    two ways of saying yes are the two buttons -- no extra dialog.
    """
    alert = NSAlert.alloc().init()
    # Phrased as a question, not a title, so it reads as a decision rather than
    # as the first pane of the challenge.
    alert.setMessageText_(f"Are you sure you want to unlock {target}?")

    lines = []
    if next_step:
        lines.append(f"You'll have to {next_step} first.")
    if plan.offer_choice:
        lines.append(f"Then choose how long you get: {plan.minutes} minutes, "
                     f"or until you lock it again yourself.")
    elif plan.minutes is None:
        lines.append("It stays unlocked until you lock it again, "
                     "or until 06:00 tomorrow.")
    else:
        lines.append(f"It re-locks itself after {plan.minutes} minutes.")
    alert.setInformativeText_(" ".join(lines))

    if plan.offer_choice:
        alert.addButtonWithTitle_(f"Unlock for {plan.minutes} min")
        alert.addButtonWithTitle_("Until I re-lock it")
        alert.addButtonWithTitle_("Cancel")
        choice = alert.runModal()
        return {NSAlertFirstButtonReturn: TIMED,
                NSAlertFirstButtonReturn + 1: UNTIMED}.get(choice, CANCELLED)

    alert.addButtonWithTitle_("Unlock" if plan.minutes is None
                              else f"Unlock for {plan.minutes} min")
    alert.addButtonWithTitle_("Cancel")
    if alert.runModal() != NSAlertFirstButtonReturn:
        return CANCELLED
    return UNTIMED if plan.minutes is None else TIMED


# --- tier 2: arithmetic ----------------------------------------------------

def arithmetic(target: str, minutes: int, digits: int, operations: list[str]) -> bool:
    problem = C.make_sum(digits, operations)

    accessory = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 58))
    accessory.addSubview_(_label(NSMakeRect(0, 34, 300, 20),
                                 f"{problem.question} =", size=20, secondary=False))
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 26))
    field.setPlaceholderString_("your answer")
    accessory.addSubview_(field)

    alert = NSAlert.alloc().init()
    alert.setMessageText_(f"Unlock {target}")
    alert.setInformativeText_("Solve it to continue.")
    alert.setAccessoryView_(accessory)
    alert.addButtonWithTitle_("Unlock")
    alert.addButtonWithTitle_("Cancel")
    alert.window().setInitialFirstResponder_(field)

    if alert.runModal() != NSAlertFirstButtonReturn:
        return False
    if C.mark_sum(field.stringValue(), problem.answer):
        return True

    wrong = NSAlert.alloc().init()
    wrong.setMessageText_("Not quite.")
    wrong.setInformativeText_(f"{problem.question} = {problem.answer}. Try again if you like.")
    wrong.addButtonWithTitle_("OK")
    wrong.runModal()
    return False


# --- tier 3: transcription -------------------------------------------------

def transcription(target: str, minutes: int, passage_name: str, passage: str,
                  *, typo_budget_ratio: float = 0.02, case: bool = True,
                  whitespace: bool = True, punctuation: bool = True,
                  carried_text: str = "") -> tuple[bool, str]:
    """Returns (passed, whatever was typed) so a retry can keep the typing."""
    accessory = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 430))

    accessory.addSubview_(_label(NSMakeRect(0, 410, W, 16),
                                 f"From {C.title_for(passage_name)} — "
                                 f"{len(passage.split())} words"))
    passage_scroll, _ = _scrolling_text(
        NSMakeRect(0, 220, W, 186), editable=False,
        font=NSFont.fontWithName_size_("Georgia", 13) or NSFont.systemFontOfSize_(13),
        text=passage)
    accessory.addSubview_(passage_scroll)

    accessory.addSubview_(_label(NSMakeRect(0, 196, W, 16), "Type it out below:"))
    typing_scroll, typing = _scrolling_text(
        NSMakeRect(0, 0, W, 190), editable=True,
        font=NSFont.userFixedPitchFontOfSize_(12) or NSFont.systemFontOfSize_(12),
        text=carried_text)
    accessory.addSubview_(typing_scroll)

    alert = NSAlert.alloc().init()
    alert.setMessageText_(f"Unlock {target}")
    alert.setInformativeText_("Transcribe the passage to continue.")
    alert.setAccessoryView_(accessory)
    alert.addButtonWithTitle_("Submit")
    alert.addButtonWithTitle_("Give up")
    alert.window().setInitialFirstResponder_(typing)

    if alert.runModal() != NSAlertFirstButtonReturn:
        return False, typing.string()

    typed = typing.string()
    marking = C.mark_transcription(typed, passage, typo_budget_ratio=typo_budget_ratio,
                                   case=case, whitespace=whitespace, punctuation=punctuation)
    if marking.passed:
        return True, typed

    if marking.progress < 0.95:
        detail = (f"You're about {marking.progress:.0%} of the way through "
                  f"({marking.typed_chars} of {marking.target_chars} characters).")
    else:
        detail = (f"{marking.distance} characters off; up to {marking.allowed} "
                  f"are allowed. Close — check the end.")
    again = NSAlert.alloc().init()
    again.setMessageText_("Not there yet.")
    again.setInformativeText_(detail)
    again.addButtonWithTitle_("Keep typing")
    again.addButtonWithTitle_("Give up")
    keep = again.runModal() == NSAlertFirstButtonReturn
    return False, (typed if keep else "")
