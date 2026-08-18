from providers.base import InvoiceProvider


def get_enabled_providers() -> list[InvoiceProvider]:
    from providers.ovh import OvhProvider
    from providers.scaleway import ScalewayProvider
    from providers.infomaniak import InfomaniakProvider
    from providers.microsoft365 import Microsoft365Provider
    from providers.qonto import QontoProvider
    from providers.atlassian_mail import AtlassianMailProvider
    from providers.starlink_mail import StarlinkMailProvider
    from providers.mistral_mail import MistralMailProvider
    from providers.google_workspace_mail import GoogleWorkspaceMailProvider
    from providers.alan_mail import AlanMailProvider
    from providers.mailjet_mail import MailjetMailProvider
    from providers.anthropic_mail import AnthropicMailProvider
    from providers.certigna_mail import CertignaMailProvider
    from providers.clockify_mail import ClockifyMailProvider
    from providers.apple_mail import AppleMailProvider
    from providers.github_mail import GithubMailProvider
    from providers.izivia_mail import IziviaMailProvider
    from providers.pokawa_mail import PokawaMailProvider
    from providers.stubs import (
        GoogleWorkspaceStub, AnthropicStub,
        AlanStub, MailjetStub, YoutubeStub,
    )

    candidates = [
        OvhProvider(),
        ScalewayProvider(),
        InfomaniakProvider(),
        Microsoft365Provider(),
        QontoProvider(),
        AtlassianMailProvider(),
        StarlinkMailProvider(),
        MistralMailProvider(),
        GoogleWorkspaceMailProvider(),
        AlanMailProvider(),
        MailjetMailProvider(),
        AnthropicMailProvider(),
        CertignaMailProvider(),
        ClockifyMailProvider(),
        AppleMailProvider(),
        GithubMailProvider(),
        IziviaMailProvider(),
        PokawaMailProvider(),
        GoogleWorkspaceStub(),
        AnthropicStub(),
        AlanStub(),
        MailjetStub(),
        YoutubeStub(),
    ]

    import config
    if config.FREE_MOBILE_ENABLED:
        from providers.free_mobile import FreeMobileProvider
        candidates.append(FreeMobileProvider())
    if config.STARLINK_ENABLED:
        from providers.starlink import StarlinkProvider
        candidates.append(StarlinkProvider())
    if config.YOUPRICE_ENABLED:
        from providers.youprice import YoupriceProvider
        candidates.append(YoupriceProvider())
    if config.SOSH_ENABLED:
        from providers.sosh import SoshProvider
        candidates.append(SoshProvider())
    if config.QONTO_ATTACHMENTS_ENABLED:
        from providers.qonto_attachments import QontoAttachmentsProvider
        candidates.append(QontoAttachmentsProvider())

    return [p for p in candidates if p.is_enabled()]
