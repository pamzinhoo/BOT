from pathlib import Path


def test_monetization_settings_backend_is_registered_and_safe() -> None:
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    source = Path("api/routes/admin/monetization_settings_router.py").read_text(encoding="utf-8")

    assert "monetization_settings_router" in init_source
    assert "router.include_router(monetization_settings_router)" in init_source
    assert "monetization/settings" in source
    assert "shop_channel_id" in source
    assert "approval_channel_id" in source
    assert "log_channel_id" in source
    assert "dlc_announcement_channel_id" in source
    assert "publish_shop_panel" in source
    assert "refresh_shop_panel" in source
    assert "mercadopago_access_token_configured" in source
    assert "mercadopago_public_key_configured" in source
    assert "mercadopago_webhook_secret_configured" in source
    assert "readonly_env" in source
    assert "Tokens, chaves e modo Mercado Pago continuam somente no .env" in source
    assert "Nao altera registros financeiros, assinaturas, licencas, produtos ou cargos" in source

    forbidden = [
        "PaymentHistory",
        "Subscription",
        "License",
        "Product",
        "add_roles",
        "remove_roles",
        "mercadopago_access_token =",
        "mercadopago_public_key =",
        "mercadopago_webhook_secret =",
    ]
    for text in forbidden:
        assert text not in source


def test_monetization_settings_frontend_is_visible() -> None:
    page = Path("frontend/src/pages/MonetizationPage.tsx").read_text(encoding="utf-8")
    component = Path("frontend/src/components/MonetizationPaymentSettings.tsx").read_text(encoding="utf-8")

    assert "MonetizationPaymentSettings" in page
    assert "Fase 3.4" in page
    assert "Configurações da loja/pagamento" in component
    assert "Canal da loja" in component
    assert "Canal de aprovação manual" in component
    assert "Canal de logs" in component
    assert "Canal de anúncios de DLC" in component
    assert "Publicar loja" in component
    assert "Atualizar loja" in component
    assert "Chaves ficam somente no .env" in component
    assert "QRCode" not in component
    assert "access_token" not in component
