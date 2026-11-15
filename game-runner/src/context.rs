//! All provider I/O crosses this durable, single-send boundary.
use crate::{model::*, store::Store};
use anyhow::{Context, Result, bail, ensure};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use futures_util::{SinkExt, StreamExt};
use reqwest::{
    cookie::{CookieStore, Jar},
    header::{HeaderMap, HeaderName, HeaderValue, SET_COOKIE},
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
    time::{Instant, timeout},
};
use tokio_tungstenite::{
    MaybeTlsStream, WebSocketStream,
    tungstenite::{
        Error as SocketError, Message, client::IntoClientRequest, protocol::WebSocketConfig,
    },
};
use url::Url;

const MAX_BODY: usize = 16 * 1024 * 1024;

fn provider_user_agent(provider: &str) -> &'static str {
    match canonical_provider(provider) {
        // Match the reviewed clients and Endorphina's native launch info.
        "endorphina" | "mascot" | "habanero" => "Mozilla/5.0",
        "peterandsons" => "PeterAndSons-Demo-QA/1.0",
        _ => "Evidencia-Demo-Runner/0.1",
    }
}

fn wire_response(status: u16, source: &HeaderMap, bytes: Vec<u8>) -> WireResponse {
    let mut headers = source
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("[non-UTF8]").to_owned()))
        .collect::<BTreeMap<_, _>>();
    let set_cookies = source
        .get_all(SET_COOKIE)
        .iter()
        .map(|v| v.to_str().unwrap_or("[non-UTF8]").to_owned())
        .collect();
    let body = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => {
            headers.insert("x-evidencia-body-encoding".into(), "base64".into());
            STANDARD.encode(e.into_bytes())
        }
    };
    WireResponse {
        status,
        headers,
        body,
        set_cookies,
    }
}

pub struct NativeSocket {
    stream: WebSocketStream<MaybeTlsStream<TcpStream>>,
    url: String,
}

#[derive(Clone, Debug)]
pub enum SocketPayload {
    Text(String),
    Binary(Vec<u8>),
}

pub struct DecodedFrame {
    pub values: Vec<Value>,
    pub replies: Vec<SocketPayload>,
}

#[derive(Clone)]
pub struct RunContext {
    pub store: Store,
    pub round_id: String,
    provider: String,
    client: reqwest::Client,
    cookies: Arc<Jar>,
    deadline: Duration,
    steps: usize,
    relay: Option<Url>,
    #[cfg(all(windows, feature = "redtiger-bundled-http"))]
    direct_redtiger: Arc<tokio::sync::Mutex<Option<crate::redtiger_http::DirectHttp>>>,
    #[cfg(test)]
    test_origin: Option<String>,
}

pub fn validate_target(provider: &str, value: &str) -> Result<Url> {
    let url = Url::parse(value).context("invalid provider URL")?;
    ensure!(
        matches!(url.scheme(), "https" | "wss"),
        "only TLS demo endpoints are allowed"
    );
    ensure!(
        url.username().is_empty() && url.password().is_none(),
        "credentials in provider URLs are forbidden"
    );
    ensure!(
        url.port().is_none_or(|port| port == 443)
            || (provider == "1spin4win" && value == "https://gs.1spin4win.com:10443"),
        "unexpected provider port"
    );
    ensure!(
        url.fragment().is_none(),
        "provider URL fragments are forbidden"
    );
    let host = url.host_str().context("provider host missing")?;
    let allowed = match canonical_provider(provider) {
        "rubyplay" => {
            url.scheme() == "https"
                && match host {
                    "static2.eu3cdn-83.servpavloro.com" => {
                        url.path() == "/africancats/latest/static/js/game.js"
                            && url.query().is_none()
                    }
                    "srv.prrpeu3.com" => {
                        url.path() == "/init-session/demo"
                            || (url.path() == "/gameserver/demo" && url.query().is_none())
                    }
                    _ => false,
                }
        }
        "kendoo" => {
            url.scheme() == "https"
                && match host {
                    "kendoo.com" => {
                        url.query().is_none()
                            && crate::adapters::kendoo::GAMES
                                .iter()
                                .any(|(slug, _)| url.path().strip_prefix("/games/") == Some(slug))
                    }
                    "betman-demo.head.kendoo.pro" => {
                        url.path() == "/betman-demo/static/game.html"
                            || (url.query().is_none()
                                && url.path().ends_with("/demo/")
                                && crate::adapters::kendoo::GAMES.iter().any(|(_, code)| {
                                    url.path()
                                        .starts_with(&format!("/betman-demo/gs/{code}/desktop/"))
                                }))
                    }
                    _ => false,
                }
        }
        "playtech" => match (host, url.scheme()) {
            ("gpas-games.playtechone.com", "https") => {
                url.query().is_none()
                    && (matches!(url.path(), "/" | "/gpasclientconf_live.php")
                        || url.path().ends_with("/logical_bundle.php")
                        || url
                            .path()
                            .ends_with("/brands/playtechhorizon/1/json/env_config.json")
                        || (url
                            .path()
                            .starts_with("/gpasdistributed/igv/gpas_blitz10_pop/")
                            && url.path().ends_with("/packs/manifest.json")))
            }
            ("gpas-stg.playtechone.com" | "frontend.playtechhorizon.com", "https") => {
                url.path() == "/socket.io/1/"
            }
            ("gpas-stg.playtechone.com" | "frontend.playtechhorizon.com", "wss") => {
                url.query().is_none() && url.path().starts_with("/socket.io/1/websocket/")
            }
            _ => false,
        },
        "gamesglobal" => {
            url.scheme() == "https"
                && match host {
                    "www.gamesglobal.com" => url.path().starts_with("/api/launch/"),
                    "redirector32.valueactive.eu" | "redirector32.valueactive.com" => {
                        url.path() == "/Casino/Default.aspx"
                    }
                    "gamelauncheruat.gameassists.co.uk" | "gamelauncher.gameassists.co.uk" => {
                        url.path() == "/launcher/Generic"
                    }
                    "mobile32.gameassists.co.uk" | "mobile32.gameassists.com" => {
                        url.path() == "/MobileWebServices_40/casino/game/launch"
                            || url.path().starts_with("/htmlgames/game/")
                    }
                    "api32.gameassists.co.uk" => matches!(
                        url.path(),
                        "/casino/user/public/v1/accounts/login/demo"
                            | "/Shared/Communications/Public/v1/accounts/authenticate"
                            | "/casino/play/public/v1/games/module/101053/client/50300/play"
                            | "/casino/play/public/v1/games/module/101417/client/50300/play"
                    ),
                    _ => false,
                }
        }
        "habanero" => {
            url.scheme() == "https"
                && match host {
                    "gs-test.insvr.com" => {
                        url.path() == "/pf" && url.query() == Some("client=1.1.24603.707")
                    }
                    "app-test.insvr.com" => {
                        url.query().is_none()
                            && url.path().starts_with("/gamecontent/")
                            && url
                                .path()
                                .rsplit_once("/js/script0.")
                                .is_some_and(|(_, version)| {
                                    version.strip_suffix(".min.js").is_some_and(|v| {
                                        !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit())
                                    })
                                })
                    }
                    _ => false,
                }
        }
        "mascot" => {
            url.scheme() == "https"
                && host.strip_suffix(".mascot.games").is_some_and(|subdomain| {
                    !subdomain.is_empty()
                        && subdomain
                            .bytes()
                            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
                        && (host != "demo.mascot.games" || url.path().starts_with("/run/"))
                })
        }
        "spinomenal" => {
            url.scheme() == "https"
                && url.query().is_none()
                && match host {
                    "rgs-ld-demo.spinomenal.com" => url.path() == "/api/InitClientUrl",
                    "rgs-ld-demo-core.spinomenal.com" => matches!(
                        url.path(),
                        "/api/StartSlotMachine"
                            | "/api/ProcessSlotMachine"
                            | "/api/BuyFeature"
                            | "/api/Gamble"
                            | "/api/PickFreeSpins"
                    ),
                    _ => false,
                }
        }
        "amigogaming" => match (host, url.scheme()) {
            ("amigogaming.com", "https") => {
                matches!(url.path(), "/es/games" | "/es/generateDemoGameLink")
            }
            ("launch.amigogaming.com", "https") => url.path().starts_with("/session/open/sid/"),
            ("demo.amigogaming.online", "https") => url.path() == "//icasino/sessions/launch",
            ("demo.amigogaming.cloud", "https") => {
                matches!(
                    url.path(),
                    "/" | "//icasino/sessions/launch"
                        | "/organic2/websocket/launch"
                        | "/js-frontend/html5/index.html"
                ) || url.path().starts_with("/games-alt-wgl/amigo/")
            }
            ("sdemo.amigogaming.cloud", "wss") => url.path() == "/organic2/websocket/endpoint/2",
            _ => false,
        },
        "irondog" => {
            url.scheme() == "https"
                && match host {
                    "gamelauncherservice-stage.1x2networkhub.com" => {
                        url.path() == "/" && url.query().is_none()
                    }
                    "nogs-gl-stage.nyxmalta.com" => url.path() == "/game/",
                    "gp.sociumhubeurope.com" | "gp-stage.1x2hubeurope.com" => matches!(
                        url.path(),
                        "/f1x2games/getGuestID.jsp" | "/gateway/init" | "/gateway/"
                    ),
                    _ => false,
                }
        }
        "thunderspin" => {
            url.scheme() == "https"
                && match host {
                    "cu.thunderspin.net" | "stage-cu.thunderspin.net" => {
                        url.path().starts_with("/games/") || url.path().starts_with("/service/")
                    }
                    "games.thunderspin.com" => [
                        "/monstersushi/",
                        "/necronomicon/",
                        "/pyramids/",
                        "/bookofgames/",
                        "/service/",
                    ]
                    .iter()
                    .any(|prefix| url.path().starts_with(prefix)),
                    "expo.bossgs.net" => url.path().starts_with("/service/"),
                    _ => false,
                }
        }
        "1spin4win" => {
            value == "https://gs.1spin4win.com:10443"
                || (host == "gs.1spin4win.com"
                    && url.scheme() == "wss"
                    && url.path() == "/games"
                    && url.query().is_none())
        }
        "egt-digital" => matches!(
            (host, url.scheme()),
            ("games.egt-ong.com", "https") | ("game-server-demo.egt-ong.com", "wss")
        ),
        "betsoft" => {
            url.scheme() == "https"
                && match host {
                    "democasino.betsoftgaming.com" => {
                        matches!(url.path(), "/cwguestlogin.do" | "/free/base/template.jsp")
                    }
                    "games-gp3demo.betsoftgaming.com" => matches!(
                        url.path(),
                        "/Lucky7.game" | "/AtTheMovies.game" | "/RooksRevenge.game"
                    ),
                    _ => false,
                }
        }
        "evoplay" => {
            url.scheme() == "https"
                && (host.ends_with(".evoplay.games") || host.ends_with(".demo-evoplay.games"))
        }
        "ela-games" => match (host, url.scheme()) {
            ("expo.elaapi.com", "https") => {
                url.path().starts_with("/demo/") && url.query().is_none()
            }
            ("preprod.elaapi.com", "https") => matches!(url.path(), "/" | "/launcher/"),
            ("preprod.elaapi.com", "wss") => url.path() == "/gateway-game/socket.io/",
            _ => false,
        },
        "amusnet" => matches!(
            (host, url.scheme(), url.path()),
            ("amusnet.com", "https", "/api/lobby")
                | ("free-pod.games.amusnet.io", "https", "/demo/v1/launch")
                | (
                    "free-pod.games.amusnet.io" | "free-pod01.games.amusnet.io",
                    "wss",
                    "/"
                )
                | ("prod.cdn.amusnet.io", "https", "/")
        ),
        "hacksaw" => matches!(
            host,
            "static-live.hacksawgaming.com" | "rgs-demo.hacksawgaming.com"
        ),
        "endorphina" => matches!(
            host,
            "endorphina.com"
                | "edemo.endorphina.com"
                | "demo.endorphina.network"
                | "dyndemo.endorphina.network"
        ),
        "peterandsons" => matches!(host, "demo.spinart.cloud" | "cdn-demo.spinart.cloud"),
        "nolimit" => matches!(host, "demo.nolimitcdn.com" | "demo.nolimitcity.com"),
        "hardfire-kalamba" => {
            (matches!(
                host,
                "kalamba.integration.demo.kalambagames.com"
                    | "v.play.test.kl.luckycdn.net"
                    | "v.games.test.kl.luckycdn.net"
            ) && url.scheme() == "https")
                || (host == "awscdn.test.kalamba.net"
                    && url.scheme() == "https"
                    && matches!(url.path(), "/" | "/index.html"))
                || (host
                    .strip_prefix("gameserver-api-")
                    .and_then(|s| s.strip_suffix(".test.twmc8fvg.click"))
                    .is_some_and(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
                    && url.scheme() == "wss"
                    && url.path() == "/oryxreplica/")
        }
        "yggdrasil" => matches!(
            host,
            "demo.yggdrasilgaming.com" | "staticdemo.yggdrasilgaming.com"
        ),
        "belatra" => url.scheme() == "https" && host == "demo.bltrm.com",
        "microgaming" => {
            host == "api8888.maf-114.xyz"
                && url.scheme() == "https"
                && url.path().starts_with("/base/")
        }
        "elk" => matches!(
            host,
            "gamelauncher-stage.contentmedia.eu"
                | "static-stage.contentmedia.eu"
                | "gc5-stage.contentmedia.eu"
        ),
        "kagaming" => matches!(host, "gamesdemo.kaga88.com" | "rmpdemo.kaga88.com"),
        "playngo" => matches!(
            host,
            "www.playngo.com"
                | "released.playngonetwork.com"
                | "ascflyp.playngonetwork.com"
                | "cdn.playngonetwork.com"
        ),
        "netent" => match (url.scheme(), host) {
            ("wss", "showcase.evo-games.com") => url.path() == "/public/horizon",
            ("https", "games.evolution.com") => {
                url.path().starts_with("/slots/") || url.path() == "/wp-json/games/v1/start"
            }
            ("https", "showcase.evo-games.com") => {
                matches!(url.path(), "/" | "/entry" | "/config")
                    || url.path().starts_with("/frontend/evo/")
                    || url
                        .path()
                        .strip_prefix("/public/rng/dragon/servlet/CasinoGameServlet;jsession=")
                        .is_some_and(|session| {
                            !session.is_empty()
                                && session.bytes().all(|b| b.is_ascii_alphanumeric())
                        })
            }
            ("https", "affiliate0000001-static2.casinomodule.com") => {
                url.query().is_none()
                    && url.path().starts_with("/games/")
                    && url.path().ends_with(".js")
            }
            ("https", host) => host
                .strip_prefix("gserver-")
                .and_then(|rest| rest.strip_suffix(".redtiger.cash"))
                .is_some_and(|instance| {
                    instance.starts_with("evo-")
                        && instance
                            .bytes()
                            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
                        && url.query().is_none()
                        && url
                            .path()
                            .strip_prefix(&format!("/{instance}/platform/game/"))
                            .is_some_and(|suffix| matches!(suffix, "settings" | "spin"))
                }),
            _ => false,
        },
        "redtiger" => {
            url.scheme() == "https"
                && (matches!(
                    host,
                    "redtiger.com" | "jinx.prod.cmsevo.com" | "fansite.evo-games.com"
                ) || host.ends_with(".redtiger.cash"))
        }
        "playson" => matches!(
            host,
            "playson.com"
                | "xplatformwl-lrs.box-int-54f2g.com"
                | "games.box-int-54f2g.com"
                | "demo.0y81pm-c-o6pywcq.com"
        ),
        "pragmatic" => {
            host == "demogamesfree.pragmaticplay.net"
                || (host
                    .strip_prefix("demogamesfree-")
                    .and_then(|s| s.strip_suffix(".pragmaticplay.net"))
                    .is_some_and(|s| {
                        !s.is_empty()
                            && s.bytes()
                                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
                    })
                    && url.scheme() == "https"
                    && url.path().starts_with("/gs2c/common/"))
        }
        _ => false,
    };
    ensure!(
        allowed,
        "endpoint is outside the reviewed demo host allowlist for {provider}"
    );
    Ok(url)
}

pub fn validate_relay(value: &str) -> Result<Url> {
    let url = Url::parse(value).context("invalid relay URL")?;
    ensure!(
        url.scheme() == "http"
            && matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]")),
        "relay must be a local explicit HTTP proxy"
    );
    ensure!(
        url.username().is_empty() && url.password().is_none(),
        "relay credentials are not accepted"
    );
    ensure!(
        url.query().is_none() && url.fragment().is_none() && url.path() == "/",
        "relay must be an origin without query, fragment or path"
    );
    Ok(url)
}

impl RunContext {
    pub fn new(
        store: Store,
        round_id: String,
        provider: &str,
        seconds: u64,
        steps: usize,
        proxy: Option<&str>,
    ) -> Result<Self> {
        ensure!(
            (1..=300).contains(&seconds),
            "request timeout must be between 1 and 300 seconds"
        );
        ensure!(
            (1..=10_000).contains(&steps),
            "step limit must be between 1 and 10000"
        );
        let cookies = Arc::new(Jar::default());
        let mut builder = reqwest::Client::builder()
            // The same jar is applied explicitly to HTTP and WSS below. Cookie
            // scope always uses the provider URL, independent of its transport.
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .connect_timeout(Duration::from_secs(15))
            .timeout(Duration::from_secs(seconds))
            .no_proxy()
            .user_agent(provider_user_agent(provider));
        if let Some(proxy) = proxy {
            validate_relay(proxy)?;
            builder = builder.proxy(reqwest::Proxy::all(proxy)?);
        }
        Ok(Self {
            store,
            round_id,
            provider: canonical_provider(provider).into(),
            client: builder.build()?,
            cookies,
            deadline: Duration::from_secs(seconds),
            steps,
            relay: proxy.map(validate_relay).transpose()?,
            #[cfg(all(windows, feature = "redtiger-bundled-http"))]
            direct_redtiger: Arc::default(),
            #[cfg(test)]
            test_origin: None,
        })
    }
    pub fn max_steps(&self) -> usize {
        self.steps
    }
    pub fn user_agent(&self) -> &'static str {
        provider_user_agent(&self.provider)
    }
    #[cfg(test)]
    pub(crate) fn route_to_fixture(&mut self, origin: &str) -> Result<()> {
        let parsed = Url::parse(origin)?;
        ensure!(
            parsed.scheme() == "http" && matches!(parsed.host_str(), Some("127.0.0.1" | "[::1]")),
            "fixtures require local loopback"
        );
        self.test_origin = Some(parsed.origin().ascii_serialization());
        Ok(())
    }
    pub fn save_session(&self, owner: &Value) -> Result<()> {
        self.store.save_session(&self.round_id, owner)
    }
    fn url(&self, value: &str) -> Result<Url> {
        #[cfg(test)]
        if let Some(origin) = &self.test_origin {
            let u = Url::parse(value)?;
            if &u.origin().ascii_serialization() == origin {
                return Ok(u);
            }
            let reviewed = validate_target(&self.provider, value)?;
            let mut local = Url::parse(origin)?;
            local.set_path(&format!(
                "/{}{}",
                reviewed.host_str().unwrap(),
                reviewed.path()
            ));
            local.set_query(reviewed.query());
            if reviewed.scheme() == "wss" {
                local
                    .set_scheme("ws")
                    .map_err(|_| anyhow::anyhow!("invalid fixture scheme"))?;
            }
            return Ok(local);
        }
        validate_target(&self.provider, value)
    }
    fn available(&self) -> Result<()> {
        if let Some(reason) = self.store.provider_hold(&self.provider)? {
            bail!("provider has a retained hold: {reason}");
        }
        Ok(())
    }
    fn accept_cookies(&self, url: &Url, headers: &HeaderMap) {
        self.cookies
            .set_cookies(&mut headers.get_all(SET_COOKIE).iter(), url);
    }
    pub(crate) fn seed_cookie(&self, url: &str, value: &str) -> Result<()> {
        self.cookies
            .add_cookie_str(value, &validate_target(&self.provider, url)?);
        Ok(())
    }
    fn retain_access_failure(&self, label: &str, response: &WireResponse) -> Result<()> {
        if matches!(response.status, 403 | 429 | 503) {
            let kind = if response.status == 403
                && response
                    .headers
                    .get("cf-mitigated")
                    .is_some_and(|v| v.eq_ignore_ascii_case("challenge"))
            {
                "provider-declared browser challenge"
            } else {
                "access rejected; cause not established"
            };
            let reason = format!(
                "HTTP {} at {label}: {kind}; explicit operator review required",
                response.status
            );
            self.store.hold_provider(&self.provider, &reason)?;
            self.store.mark_error(&self.round_id, &reason)?;
            bail!("{reason}");
        }
        Ok(())
    }
    pub async fn get(&self, label: &str, url: &str) -> Result<WireResponse> {
        self.http(label, "GET", url, BTreeMap::new(), String::new(), false)
            .await
    }
    pub async fn json(
        &self,
        label: &str,
        url: &str,
        body: &Value,
        mut headers: BTreeMap<String, String>,
        financial: bool,
    ) -> Result<Value> {
        headers
            .entry("content-type".into())
            .or_insert_with(|| "application/json".into());
        let response = self
            .http(
                label,
                "POST",
                url,
                headers,
                serde_json::to_string(body)?,
                financial,
            )
            .await?;
        ensure!(
            (200..300).contains(&response.status),
            "HTTP status {} at {label}",
            response.status
        );
        serde_json::from_str(&response.body)
            .with_context(|| format!("invalid native JSON at {label}"))
    }
    pub async fn http(
        &self,
        label: &str,
        method: &str,
        url: &str,
        mut headers: BTreeMap<String, String>,
        body: String,
        financial: bool,
    ) -> Result<WireResponse> {
        self.available()?;
        let target = self.url(url)?;
        let cookie_url = Url::parse(url)?;
        ensure!(
            target.scheme() == "https" || cfg!(test),
            "HTTP provider endpoints require HTTPS"
        );
        let verb = reqwest::Method::from_bytes(method.as_bytes())?;
        ensure!(
            matches!(verb, reqwest::Method::GET | reqwest::Method::POST),
            "unreviewed HTTP method"
        );
        #[cfg(all(windows, feature = "redtiger-bundled-http"))]
        if (self.provider == "redtiger"
            || cfg!(feature = "spinomenal-bundled-http") && self.provider == "spinomenal")
            && self.relay.is_none() && target.scheme() == "https" {
            #[cfg(test)]
            let fixture = self.test_origin.is_some();
            #[cfg(not(test))]
            let fixture = false;
            if !fixture {
                return self
                    .direct_http_request(WireRequest {
                        label: label.into(),
                        transport: "http".into(),
                        method: method.into(),
                        url: target.to_string(),
                        headers,
                        body,
                        financial,
                    })
                    .await;
            }
        }
        if !headers.keys().any(|k| k.eq_ignore_ascii_case("cookie"))
            && let Some(cookie) = self.cookies.cookies(&cookie_url)
        {
            headers.insert("cookie".into(), cookie.to_str()?.to_owned());
        }
        if !headers.keys().any(|k| k.eq_ignore_ascii_case("user-agent")) {
            headers.insert("user-agent".into(), self.user_agent().into());
        }
        let mut map = HeaderMap::new();
        for (name, value) in &headers {
            map.insert(
                HeaderName::from_bytes(name.as_bytes())?,
                HeaderValue::from_str(value)?,
            );
        }
        let request = WireRequest {
            label: label.into(),
            transport: "http".into(),
            method: method.into(),
            url: url.into(),
            headers,
            body: body.clone(),
            financial,
        };
        let ordinal = self.store.start_exchange(&self.round_id, &request)?;
        // Once headers arrive, persist them and every retained body chunk before
        // interpretation. A process crash can therefore retain received evidence
        // even before the final WireResponse has been assembled.
        let sent = self
            .client
            .request(verb, target)
            .headers(map)
            .body(body)
            .send()
            .await;
        let mut response = match sent {
            Ok(response) => response,
            Err(error) => {
                let error =
                    anyhow::Error::new(error).context("HTTP transport failed after durable intent");
                self.store
                    .fail_exchange(&self.round_id, ordinal, &format!("{error:#}"))?;
                return Err(error);
            }
        };
        let status = response.status().as_u16();
        let received_headers = response.headers().clone();
        self.store.append_frame(
            &self.round_id,
            ordinal,
            "http_headers",
            &serde_json::to_string(&wire_response(status, &received_headers, Vec::new()))?,
        )?;
        self.accept_cookies(&cookie_url, &received_headers);
        let mut bytes = Vec::new();
        let mut body_error = None;
        loop {
            match response.chunk().await {
                Ok(Some(chunk)) => {
                    let keep = chunk.len().min(MAX_BODY.saturating_sub(bytes.len()));
                    if keep > 0 {
                        self.store.append_frame(
                            &self.round_id,
                            ordinal,
                            "http_body_base64",
                            &STANDARD.encode(&chunk[..keep]),
                        )?;
                        bytes.extend_from_slice(&chunk[..keep]);
                    }
                    if keep < chunk.len() {
                        body_error = Some((
                            "size_limit",
                            "native body exceeds 16 MiB; attempt retained for review".to_owned(),
                        ));
                        break;
                    }
                }
                Ok(None) => break,
                Err(error) => {
                    body_error = Some(("interrupted", format!("HTTP body interrupted: {error}")));
                    break;
                }
            }
        }
        let mut received = wire_response(status, &received_headers, bytes);
        if let Some((kind, reason)) = &body_error {
            received
                .headers
                .insert("x-evidencia-body-completeness".into(), (*kind).into());
            received
                .headers
                .insert("x-evidencia-body-error".into(), reason.clone());
        }
        self.store
            .finish_exchange(&self.round_id, ordinal, &received)?;
        // A partial body does not erase an already observed rejection or allow
        // automatic bootstrap recovery to treat it as a complete response.
        self.retain_access_failure(label, &received)?;
        if let Some((_, reason)) = body_error {
            self.store.mark_error(&self.round_id, &reason)?;
            bail!("{reason}");
        }
        if financial && !(200..300).contains(&received.status) {
            let reason = format!(
                "financial HTTP {} at {label}; acceptance uncertain",
                received.status
            );
            self.store.mark_error(&self.round_id, &reason)?;
            bail!("{reason}");
        }
        Ok(received)
    }

    #[cfg(all(windows, feature = "redtiger-bundled-http"))]
    async fn direct_http_request(&self, request: WireRequest) -> Result<WireResponse> {
        let mut active = self.direct_redtiger.lock().await;
        if active.is_none() {
            let root = self.store.root().to_owned();
            *active = Some(tokio::task::spawn_blocking(move || {
                crate::redtiger_http::DirectHttp::new(&root)
            }).await??);
        }
        let ordinal = self.store.start_exchange(&self.round_id, &request)?;
        let exchange = async {
            timeout(
                self.deadline,
                active.as_mut().unwrap().exchange(&request, self.deadline),
            )
            .await
            .context("embedded HTTP deadline")?
        }
        .await;
        let response = match exchange {
            Ok(response) => response,
            Err(error) => {
                self.store
                    .fail_exchange(&self.round_id, ordinal, &format!("{error:#}"))?;
                return Err(error);
            }
        };
        self.store
            .finish_exchange(&self.round_id, ordinal, &response)?;
        self.retain_access_failure(&request.label, &response)?;
        if response
            .headers
            .contains_key("x-evidencia-body-completeness")
            || request.financial && !(200..300).contains(&response.status)
        {
            let reason = format!("incomplete embedded HTTP exchange at {}", request.label);
            self.store.mark_error(&self.round_id, &reason)?;
            bail!("{reason}");
        }
        Ok(response)
    }

    #[cfg(all(windows, feature = "redtiger-bundled-http"))]
    pub(crate) async fn close_direct_http(&self) {
        let active = self.direct_redtiger.lock().await.take();
        if let Some(http) = active {
            http.close().await;
        }
    }

    pub async fn websocket(
        &self,
        url: &str,
        origin: &str,
        subprotocol: Option<&str>,
        headers: BTreeMap<String, String>,
    ) -> Result<NativeSocket> {
        self.available()?;
        let target = self.url(url)?;
        ensure!(
            target.scheme() == "wss" || (cfg!(test) && target.scheme() == "ws"),
            "native sockets require WSS"
        );
        self.url(origin)?;
        let mut request = target.as_str().into_client_request()?;
        request.headers_mut().insert("Origin", origin.parse()?);
        request
            .headers_mut()
            .insert("User-Agent", self.user_agent().parse()?);
        if let Some(value) = subprotocol {
            request
                .headers_mut()
                .insert("Sec-WebSocket-Protocol", value.parse()?);
        }
        let mut cookie_url = Url::parse(url)?;
        cookie_url
            .set_scheme("https")
            .map_err(|_| anyhow::anyhow!("invalid cookie URL"))?;
        if let Some(cookie) = self.cookies.cookies(&cookie_url) {
            request.headers_mut().insert("Cookie", cookie);
        }
        for (key, value) in &headers {
            request.headers_mut().insert(
                HeaderName::from_bytes(key.as_bytes())?,
                HeaderValue::from_str(value)?,
            );
        }
        let handshake_headers = request
            .headers()
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("[non-UTF8]").to_owned()))
            .collect();
        let wire = WireRequest {
            label: "websocket_handshake".into(),
            transport: "websocket".into(),
            method: "CONNECT".into(),
            url: url.into(),
            headers: handshake_headers,
            body: String::new(),
            financial: false,
        };
        let ordinal = self.store.start_exchange(&self.round_id, &wire)?;
        let config = WebSocketConfig::default()
            .max_message_size(Some(MAX_BODY))
            .max_frame_size(Some(MAX_BODY));
        let result = timeout(self.deadline, async {
            if let Some(relay) = &self.relay {
                let stream = connect_tunnel(relay, &target).await?;
                Ok::<_, anyhow::Error>(
                    tokio_tungstenite::client_async_tls_with_config(
                        request,
                        stream,
                        Some(config),
                        None,
                    )
                    .await?,
                )
            } else {
                Ok(
                    tokio_tungstenite::connect_async_with_config(request, Some(config), true)
                        .await?,
                )
            }
        })
        .await;
        match result {
            Ok(Ok((stream, response))) => {
                let received =
                    wire_response(response.status().as_u16(), response.headers(), Vec::new());
                self.store
                    .finish_exchange(&self.round_id, ordinal, &received)?;
                self.accept_cookies(&cookie_url, response.headers());
                Ok(NativeSocket {
                    stream,
                    url: url.into(),
                })
            }
            Ok(Err(error)) => {
                if let Some(SocketError::Http(response)) = error.downcast_ref::<SocketError>() {
                    let body = response.body().clone().unwrap_or_default();
                    let mut received =
                        wire_response(response.status().as_u16(), response.headers(), body);
                    // Tungstenite exposes bytes buffered while parsing the
                    // handshake, not necessarily the full rejection body.
                    received.headers.insert(
                        "x-evidencia-body-completeness".into(),
                        "handshake-buffered".into(),
                    );
                    self.store
                        .finish_exchange(&self.round_id, ordinal, &received)?;
                    self.accept_cookies(&cookie_url, response.headers());
                    self.retain_access_failure("websocket_handshake", &received)?;
                    let message =
                        format!("native WSS handshake rejected: HTTP {}", received.status);
                    self.store.mark_error(&self.round_id, &message)?;
                    bail!("{message}");
                }
                let message = "native WSS handshake failed: transport/protocol error";
                self.store.fail_exchange(&self.round_id, ordinal, message)?;
                bail!("{message}")
            }
            Err(_) => {
                let message = "native WSS handshake failed: timeout";
                self.store.fail_exchange(&self.round_id, ordinal, message)?;
                bail!("{message}")
            }
        }
    }
    pub async fn ws_codec<F>(
        &self,
        socket: &mut NativeSocket,
        label: &str,
        payload: SocketPayload,
        financial: bool,
        request_id: Option<&str>,
        mut decode: F,
    ) -> Result<Value>
    where
        F: FnMut(&SocketPayload) -> Result<Vec<Value>> + Send,
    {
        self.ws_codec_controlled(
            socket,
            label,
            payload,
            financial,
            request_id,
            move |frame| {
                Ok(DecodedFrame {
                    values: decode(frame)?,
                    replies: Vec::new(),
                })
            },
        )
        .await
    }
    /// Application-level control replies stay in the original journal exchange.
    /// Each reply is committed before transmission and shares the original deadline.
    pub async fn ws_codec_controlled<F>(
        &self,
        socket: &mut NativeSocket,
        label: &str,
        payload: SocketPayload,
        financial: bool,
        request_id: Option<&str>,
        decode: F,
    ) -> Result<Value>
    where
        F: FnMut(&SocketPayload) -> Result<DecodedFrame> + Send,
    {
        self.ws_exchange(socket, label, Some(payload), financial, request_id, decode)
            .await
    }

    pub async fn ws_expect_text(
        &self,
        socket: &mut NativeSocket,
        label: &str,
        expected: &str,
    ) -> Result<()> {
        self.ws_exchange(socket, label, None, false, None, |frame| {
            ensure!(
                matches!(frame, SocketPayload::Text(text) if text == expected),
                "unexpected native socket greeting"
            );
            Ok(DecodedFrame {
                values: vec![json!(expected)],
                replies: Vec::new(),
            })
        })
        .await?;
        Ok(())
    }

    pub(crate) async fn ws_exchange<F>(
        &self,
        socket: &mut NativeSocket,
        label: &str,
        payload: Option<SocketPayload>,
        financial: bool,
        request_id: Option<&str>,
        mut decode: F,
    ) -> Result<Value>
    where
        F: FnMut(&SocketPayload) -> Result<DecodedFrame> + Send,
    {
        self.available()?;
        let (body, headers, message) = match payload {
            Some(SocketPayload::Text(text)) => {
                ensure!(
                    text.len() <= MAX_BODY,
                    "native outgoing frame exceeds 16 MiB"
                );
                (
                    text.clone(),
                    BTreeMap::new(),
                    Some(Message::Text(text.into())),
                )
            }
            Some(SocketPayload::Binary(bytes)) => {
                ensure!(
                    bytes.len() <= MAX_BODY,
                    "native outgoing frame exceeds 16 MiB"
                );
                (
                    STANDARD.encode(&bytes),
                    BTreeMap::from([("x-evidencia-body-encoding".into(), "base64".into())]),
                    Some(Message::Binary(bytes.into())),
                )
            }
            None => (String::new(), BTreeMap::new(), None),
        };
        let intent = WireRequest {
            label: label.into(),
            transport: "websocket".into(),
            method: if message.is_some() { "SEND" } else { "RECEIVE" }.into(),
            url: socket.url.clone(),
            headers,
            body,
            financial,
        };
        let ordinal = self.store.start_exchange(&self.round_id, &intent)?;
        let mut messages = Vec::new();
        let mut received_bytes = 0usize;
        let mut control_replies = 0usize;
        let result: Result<Value> = async {
            if let Some(message) = message {
                timeout(self.deadline, socket.stream.send(message))
                    .await
                    .context("WSS send timed out")??;
            }
            let deadline = Instant::now() + self.deadline;
            for _ in 0..100 {
                let remaining = deadline.saturating_duration_since(Instant::now());
                ensure!(!remaining.is_zero(), "WSS response timed out");
                let frame = timeout(remaining, socket.stream.next())
                    .await
                    .context("WSS response timed out")?
                    .context("WSS closed without correlated response")??;
                // Commit the original frame before interpreting it, including malformed JSON.
                let (kind, raw) = match &frame {
                    Message::Text(s) => ("text", s.to_string()),
                    Message::Binary(b) => ("binary_base64", STANDARD.encode(b)),
                    Message::Ping(b) => ("ping_base64", STANDARD.encode(b)),
                    Message::Pong(b) => ("pong_base64", STANDARD.encode(b)),
                    Message::Close(c) => ("close", format!("{c:?}")),
                    Message::Frame(f) => ("frame", format!("{f:?}")),
                };
                self.store
                    .append_frame(&self.round_id, ordinal, kind, &raw)?;
                received_bytes = received_bytes.saturating_add(raw.len());
                ensure!(
                    received_bytes <= MAX_BODY,
                    "native WSS exchange exceeds 16 MiB"
                );
                match frame {
                    Message::Text(_) | Message::Binary(_) => {
                        let native = match frame {
                            Message::Text(text) => SocketPayload::Text(text.to_string()),
                            Message::Binary(bytes) => SocketPayload::Binary(bytes.to_vec()),
                            _ => unreachable!("matched data frame above"),
                        };
                        let decoded = decode(&native)?;
                        for reply in decoded.replies {
                            control_replies += 1;
                            ensure!(control_replies <= 100, "too many native control replies");
                            let (kind, raw, message) = match reply {
                                SocketPayload::Text(text) => {
                                    ensure!(
                                        text.len() <= MAX_BODY,
                                        "native control reply exceeds 16 MiB"
                                    );
                                    (
                                        "sent_control_text",
                                        text.clone(),
                                        Message::Text(text.into()),
                                    )
                                }
                                SocketPayload::Binary(bytes) => {
                                    ensure!(
                                        bytes.len() <= MAX_BODY,
                                        "native control reply exceeds 16 MiB"
                                    );
                                    (
                                        "sent_control_binary_base64",
                                        STANDARD.encode(&bytes),
                                        Message::Binary(bytes.into()),
                                    )
                                }
                            };
                            received_bytes = received_bytes.saturating_add(raw.len());
                            ensure!(
                                received_bytes <= MAX_BODY,
                                "native WSS exchange exceeds 16 MiB"
                            );
                            self.store
                                .append_frame(&self.round_id, ordinal, kind, &raw)?;
                            timeout(
                                deadline.saturating_duration_since(Instant::now()),
                                socket.stream.send(message),
                            )
                            .await
                            .context("WSS control reply timed out")??;
                        }
                        for value in decoded.values {
                            messages.push(value.clone());
                            let matches = request_id.is_none_or(|id| {
                                value
                                    .get("requestId")
                                    .or_else(|| value.get("id"))
                                    .is_some_and(|v| {
                                        v.as_str()
                                            .map(str::to_owned)
                                            .unwrap_or_else(|| v.to_string())
                                            == id
                                    })
                            });
                            if matches {
                                return Ok(value);
                            }
                        }
                    }
                    Message::Ping(data) => {
                        timeout(
                            deadline.saturating_duration_since(Instant::now()),
                            socket.stream.send(Message::Pong(data)),
                        )
                        .await
                        .context("WSS pong timed out")??;
                    }
                    Message::Pong(_) => {}
                    _ => bail!("unexpected native WSS frame"),
                }
            }
            bail!("no correlated WSS response within 100 frames")
        }
        .await;
        match result {
            Ok(value) => {
                self.store.finish_exchange(
                    &self.round_id,
                    ordinal,
                    &WireResponse {
                        status: 200,
                        headers: BTreeMap::new(),
                        body: serde_json::to_string(&json!({"messages":messages}))?,
                        set_cookies: Vec::new(),
                    },
                )?;
                Ok(value)
            }
            Err(error) => {
                if !messages.is_empty() {
                    self.store.finish_exchange(
                        &self.round_id,
                        ordinal,
                        &WireResponse {
                            status: 0,
                            headers: BTreeMap::from([(
                                "x-evidencia-incomplete".into(),
                                "true".into(),
                            )]),
                            body: serde_json::to_string(&json!({"messages":messages}))?,
                            set_cookies: Vec::new(),
                        },
                    )?;
                    self.store
                        .mark_error(&self.round_id, &format!("{error:#}"))?;
                } else {
                    self.store
                        .fail_exchange(&self.round_id, ordinal, &format!("{error:#}"))?;
                }
                Err(error)
            }
        }
    }
    pub async fn ws_text_decoded(
        &self,
        socket: &mut NativeSocket,
        label: &str,
        payload: &str,
        financial: bool,
        request_id: Option<&str>,
        decode: fn(&str) -> Result<Value>,
    ) -> Result<Value> {
        self.ws_codec(
            socket,
            label,
            SocketPayload::Text(payload.into()),
            financial,
            request_id,
            move |payload| match payload {
                SocketPayload::Text(text) => Ok(vec![decode(text)?]),
                SocketPayload::Binary(_) => bail!("unexpected binary frame for text codec"),
            },
        )
        .await
    }
    pub async fn ws_json(
        &self,
        socket: &mut NativeSocket,
        label: &str,
        request: &Value,
        financial: bool,
        request_id: Option<&str>,
    ) -> Result<Value> {
        self.ws_codec(
            socket,
            label,
            SocketPayload::Text(serde_json::to_string(request)?),
            financial,
            request_id,
            |payload| match payload {
                SocketPayload::Text(text) => Ok(vec![
                    serde_json::from_str(text).context("invalid WSS JSON")?,
                ]),
                SocketPayload::Binary(_) => bail!("unexpected native WSS binary frame"),
            },
        )
        .await
    }
}

async fn connect_tunnel(relay: &Url, target: &Url) -> Result<TcpStream> {
    let host = relay
        .host_str()
        .context("relay host missing")?
        .trim_matches(['[', ']']);
    let mut stream = TcpStream::connect((
        host,
        relay
            .port_or_known_default()
            .context("relay port missing")?,
    ))
    .await
    .context("local relay connection failed")?;
    stream.set_nodelay(true)?;
    let authority = format!("{}:443", target.host_str().context("target host missing")?);
    stream
        .write_all(format!("CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n").as_bytes())
        .await?;
    let mut response = Vec::new();
    while !response.ends_with(b"\r\n\r\n") {
        ensure!(response.len() < 16_384, "relay CONNECT headers too large");
        let mut byte = [0u8];
        stream
            .read_exact(&mut byte)
            .await
            .context("relay closed CONNECT")?;
        response.push(byte[0]);
    }
    let text = std::str::from_utf8(&response).context("invalid relay CONNECT response")?;
    let mut status = text
        .lines()
        .next()
        .context("missing relay CONNECT status")?
        .split_whitespace();
    ensure!(
        matches!(status.next(), Some("HTTP/1.1" | "HTTP/1.0")) && status.next() == Some("200"),
        "local relay rejected CONNECT; no direct fallback"
    );
    Ok(stream)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;
    fn fixture() -> (tempfile::TempDir, RunContext) {
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        let inventory:InventorySnapshot=serde_json::from_value(json!({"id":"test","sources":[],"providers":[{"id":"hacksaw","name":"Hacksaw","ready":true,"campaign_eligible":true,"games":[{"id":"2405","name":"Demo","ready":true,"modes":[{"key":"normal","type":"normal","label":"Normal"}]}]}]})).unwrap();
        store.install_inventory(&inventory).unwrap();
        let plan = CampaignPlan {
            schema_version: 1,
            id: "transport-fixture".into(),
            inventory_id: inventory.id,
            coverage: None,
            jobs: vec![Job {
                provider: "hacksaw".into(),
                game: "2405".into(),
                mode: "normal".into(),
                samples: 1,
                settings: Value::Null,
            }],
        };
        store.create_campaign(&plan).unwrap();
        let round = store
            .create_round(&RoundSpec {
                campaign_id: plan.id,
                inventory_id: plan.inventory_id,
                job_index: 0,
                sample_index: 0,
                provider: "hacksaw".into(),
                game: "2405".into(),
                mode: "normal".into(),
                kind: ModeKind::Normal,
                settings: Value::Null,
            })
            .unwrap();
        let ctx = RunContext::new(store, round.id, "hacksaw", 2, 10, None).unwrap();
        ctx.save_session(&json!({"owner":"offline-only"})).unwrap();
        (dir, ctx)
    }
    async fn read_headers(stream: &mut TcpStream) -> Vec<u8> {
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") {
            let mut byte = [0u8];
            stream.read_exact(&mut byte).await.unwrap();
            request.push(byte[0]);
            assert!(request.len() < 16384);
        }
        request
    }
    #[test]
    fn only_official_demo_hosts_and_tls_are_allowed() {
        assert!(
            validate_target("hacksaw", "https://rgs-demo.hacksawgaming.com/api/play/bet").is_ok()
        );
        assert!(
            validate_target(
                "hacksaw",
                "https://rgs-demo.hacksawgaming.com.evil.invalid/api"
            )
            .is_err()
        );
        assert!(validate_target("hacksaw", "http://rgs-demo.hacksawgaming.com/api").is_err());
        assert!(
            validate_target(
                "hacksaw",
                "https://user:pass@rgs-demo.hacksawgaming.com/api"
            )
            .is_err()
        );
        assert!(validate_target("hacksaw", "https://127.0.0.1/api").is_err());
        assert!(validate_target("hacksaw", "https://rgs-demo.hacksawgaming.com:8443/api").is_err());
    }
    #[tokio::test]
    async fn http_lost_response_is_single_send_and_durable() {
        let (_dir, mut ctx) = fixture();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        ctx.test_origin = Some(origin.clone());
        let (store, id) = (ctx.store.clone(), ctx.round_id.clone());
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_headers(&mut stream).await;
            let recorded = store.exchanges(&id).unwrap();
            assert_eq!(recorded.len(), 1);
            assert!(recorded[0].response.is_none());
            assert!(recorded[0].request.financial);
            drop(stream);
            assert!(
                timeout(Duration::from_millis(250), listener.accept())
                    .await
                    .is_err(),
                "unexpected automatic retry"
            );
        });
        assert!(
            ctx.http(
                "paid_entry",
                "POST",
                &origin,
                BTreeMap::new(),
                "{}".into(),
                true
            )
            .await
            .is_err()
        );
        assert_eq!(
            ctx.store.round(&ctx.round_id).unwrap().status,
            RoundStatus::Uncertain
        );
        assert!(
            ctx.http(
                "do_not_retry",
                "POST",
                &origin,
                BTreeMap::new(),
                "{}".into(),
                true
            )
            .await
            .is_err()
        );
        server.await.unwrap();
        assert_eq!(
            Store::open(ctx.store.root())
                .unwrap()
                .exchanges(&ctx.round_id)
                .unwrap()
                .len(),
            1
        );
    }
    #[tokio::test]
    async fn interrupted_http_retains_status_headers_bytes_and_financial_owner() {
        let (_dir, mut ctx) = fixture();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        ctx.route_to_fixture(&origin).unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_headers(&mut stream).await;
            stream.write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 100\r\nConnection: close\r\nX-Native-Receipt: received\r\nSet-Cookie: sid=retained; Path=/\r\n\r\npartial").await.unwrap();
            stream.shutdown().await.unwrap();
        });
        assert!(
            ctx.http(
                "paid_entry",
                "POST",
                &origin,
                BTreeMap::new(),
                String::new(),
                true
            )
            .await
            .is_err()
        );
        server.await.unwrap();
        let reopened = Store::open(ctx.store.root()).unwrap();
        let exchanges = reopened.exchanges(&ctx.round_id).unwrap();
        assert_eq!(exchanges.len(), 1);
        let response = exchanges[0]
            .response
            .as_ref()
            .expect("partial HTTP response discarded");
        assert_eq!(response.status, 403);
        assert_eq!(response.body, "partial");
        assert_eq!(response.headers["x-native-receipt"], "received");
        assert_eq!(
            response.headers["x-evidencia-body-completeness"],
            "interrupted"
        );
        assert_eq!(response.set_cookies.len(), 1);
        assert!(reopened.provider_hold("hacksaw").unwrap().is_some());
        assert_eq!(
            reopened.round(&ctx.round_id).unwrap().status,
            RoundStatus::Uncertain
        );
        assert_eq!(
            reopened.session(&ctx.round_id).unwrap(),
            Some(json!({"owner":"offline-only"}))
        );
    }
    #[tokio::test]
    async fn oversized_http_retains_bounded_prefix_and_rejection_status() {
        let (_dir, original) = fixture();
        // Durably storing the 16 MiB prefix performs real SQLite commits. Keep
        // the fixture deadline independent of slow CI filesystem throughput.
        let mut ctx = RunContext::new(
            original.store.clone(),
            original.round_id.clone(),
            "hacksaw",
            30,
            10,
            None,
        )
        .unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        ctx.route_to_fixture(&origin).unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_headers(&mut stream).await;
            stream.write_all(format!("HTTP/1.1 403 Forbidden\r\nContent-Length: {}\r\nConnection: close\r\nX-Native-Receipt: large\r\n\r\n", MAX_BODY + 1).as_bytes()).await.unwrap();
            let _ = stream.write_all(&vec![b'x'; MAX_BODY + 1]).await;
            let _ = stream.shutdown().await;
        });
        assert!(ctx.get("bootstrap", &origin).await.is_err());
        server.await.unwrap();
        let exchanges = ctx.store.exchanges(&ctx.round_id).unwrap();
        let response = exchanges[0]
            .response
            .as_ref()
            .expect("oversized response discarded");
        assert_eq!(response.status, 403);
        assert_eq!(response.body.len(), MAX_BODY);
        assert!(response.body.bytes().all(|b| b == b'x'));
        assert_eq!(
            response.headers["x-evidencia-body-completeness"],
            "size_limit"
        );
        assert!(ctx.store.provider_hold("hacksaw").unwrap().is_some());
    }
    #[tokio::test]
    async fn malformed_http_json_is_retained_before_parsing() {
        let (_dir, mut ctx) = fixture();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        ctx.test_origin = Some(origin.clone());
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let headers = String::from_utf8(read_headers(&mut stream).await).unwrap();
            let length = headers
                .lines()
                .filter_map(|line| line.split_once(':'))
                .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
                .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                .unwrap_or(0);
            let mut request_body = vec![0; length];
            // Unread POST bytes can cause a reset on close instead of delivering the reply.
            stream.read_exact(&mut request_body).await.unwrap();
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\ninvalid",
                )
                .await
                .unwrap();
            stream.shutdown().await.unwrap();
        });
        let error = ctx
            .json("paid_entry", &origin, &json!({}), BTreeMap::new(), true)
            .await
            .unwrap_err();
        assert!(
            error.to_string().contains("invalid native JSON"),
            "{error:#}"
        );
        server.await.unwrap();
        assert_eq!(
            ctx.store.exchanges(&ctx.round_id).unwrap()[0]
                .response
                .as_ref()
                .unwrap()
                .body,
            "invalid"
        );
    }
    #[tokio::test]
    async fn websocket_frames_survive_even_when_json_is_invalid() {
        let (_dir, ctx) = fixture();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("ws://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            socket.next().await.unwrap().unwrap();
            socket
                .send(Message::Text("{\"event\":\"native-push\"}".into()))
                .await
                .unwrap();
            socket
                .send(Message::Text("{malformed-financial-response".into()))
                .await
                .unwrap();
        });
        let stream = TcpStream::connect(listener_address(&url)).await.unwrap();
        let (stream, _) = tokio_tungstenite::client_async(&url, MaybeTlsStream::Plain(stream))
            .await
            .unwrap();
        let mut socket = NativeSocket { stream, url };
        assert!(
            ctx.ws_json(
                &mut socket,
                "paid_entry",
                &json!({"requestId":7}),
                true,
                Some("7")
            )
            .await
            .is_err()
        );
        server.await.unwrap();
        let reopened = Store::open(ctx.store.root()).unwrap();
        let exchanges = reopened.exchanges(&ctx.round_id).unwrap();
        assert_eq!(exchanges[0].frames.len(), 2);
        assert_eq!(exchanges[0].frames[1].body, "{malformed-financial-response");
        assert_eq!(
            reopened.round(&ctx.round_id).unwrap().status,
            RoundStatus::Uncertain
        );
    }
    fn listener_address(url: &str) -> String {
        url.strip_prefix("ws://").unwrap().into()
    }
    #[tokio::test]
    #[allow(
        clippy::result_large_err,
        reason = "tungstenite fixes the callback error type to an HTTP response"
    )]
    async fn generated_http_session_survives_websocket_and_is_isolated() {
        let (_dir, mut ctx) = fixture();
        let (_other_dir, mut other) = fixture();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        ctx.route_to_fixture(&origin).unwrap();
        other.route_to_fixture(&origin).unwrap();
        let user_agent = ctx.user_agent();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let request = String::from_utf8(read_headers(&mut stream).await).unwrap();
            assert!(!request.to_ascii_lowercase().contains("\r\ncookie:"));
            assert!(request.contains(user_agent));
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\nSet-Cookie: sid=initial; Path=/api/; Secure; HttpOnly\r\nSet-Cookie: unused=private; Path=/other/; Secure\r\n\r\nOK").await.unwrap();
            stream.shutdown().await.unwrap();

            let (stream, _) = listener.accept().await.unwrap();
            let socket = tokio_tungstenite::accept_hdr_async(stream, move |request: &tokio_tungstenite::tungstenite::handshake::server::Request, mut response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                assert_eq!(request.headers()["cookie"], "sid=initial");
                assert_eq!(request.headers()["user-agent"], user_agent);
                response.headers_mut().append(SET_COOKIE, "sid=rotated; Path=/api/; Secure; HttpOnly".parse().unwrap());
                response.headers_mut().append(SET_COOKIE, "socket=ready; Path=/api/; Secure".parse().unwrap());
                Ok(response)
            }).await.unwrap();

            let (mut stream, _) = listener.accept().await.unwrap();
            let request = String::from_utf8(read_headers(&mut stream).await).unwrap();
            let cookie = request
                .lines()
                .filter_map(|l| l.split_once(':'))
                .find(|(k, _)| k.eq_ignore_ascii_case("cookie"))
                .unwrap()
                .1;
            assert!(cookie.contains("sid=rotated") && cookie.contains("socket=ready"));
            assert!(!cookie.contains("initial") && !cookie.contains("unused"));
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
                .await
                .unwrap();
            stream.shutdown().await.unwrap();

            let (mut stream, _) = listener.accept().await.unwrap();
            let request = String::from_utf8(read_headers(&mut stream).await).unwrap();
            assert!(
                !request.to_ascii_lowercase().contains("\r\ncookie:"),
                "new session inherited cookies"
            );
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
                .await
                .unwrap();
            stream.shutdown().await.unwrap();
            drop(socket);
        });
        let url = "https://rgs-demo.hacksawgaming.com/api/session";
        let response = ctx.get("session_bootstrap", url).await.unwrap();
        assert_eq!(response.set_cookies.len(), 2);
        let socket = ctx
            .websocket(
                "wss://rgs-demo.hacksawgaming.com/api/socket",
                "https://rgs-demo.hacksawgaming.com",
                None,
                BTreeMap::new(),
            )
            .await
            .unwrap();
        ctx.get("same_session", url).await.unwrap();
        other.get("independent_session", url).await.unwrap();
        server.await.unwrap();
        drop(socket);
        let records = ctx.store.exchanges(&ctx.round_id).unwrap();
        assert_eq!(records[1].response.as_ref().unwrap().set_cookies.len(), 2);
        assert_eq!(
            records[0].request.headers["user-agent"],
            records[1].request.headers["user-agent"]
        );
    }
    #[tokio::test]
    async fn websocket_403_retains_response_and_declared_challenge_without_retry() {
        for challenge in [false, true] {
            let (_dir, mut ctx) = fixture();
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            ctx.route_to_fixture(&format!("http://{}", listener.local_addr().unwrap()))
                .unwrap();
            let server = tokio::spawn(async move {
                let (mut stream, _) = listener.accept().await.unwrap();
                read_headers(&mut stream).await;
                let mitigation = if challenge {
                    "cf-mitigated: challenge\r\n"
                } else {
                    ""
                };
                stream.write_all(format!("HTTP/1.1 403 Forbidden\r\nContent-Length: 6\r\nConnection: close\r\n{mitigation}\r\ndenied").as_bytes()).await.unwrap();
                stream.shutdown().await.unwrap();
                assert!(
                    timeout(Duration::from_millis(250), listener.accept())
                        .await
                        .is_err(),
                    "handshake automatically retried"
                );
            });
            let result = ctx
                .websocket(
                    "wss://rgs-demo.hacksawgaming.com/api/socket",
                    "https://rgs-demo.hacksawgaming.com",
                    None,
                    BTreeMap::new(),
                )
                .await;
            assert!(result.is_err());
            server.await.unwrap();
            let records = ctx.store.exchanges(&ctx.round_id).unwrap();
            assert_eq!(records.len(), 1);
            let received = records[0]
                .response
                .as_ref()
                .expect("HTTP rejection was discarded");
            assert_eq!(received.status, 403);
            assert_eq!(
                received.headers["x-evidencia-body-completeness"],
                "handshake-buffered"
            );
            assert_eq!(received.headers.contains_key("cf-mitigated"), challenge);
            let hold = ctx.store.provider_hold("hacksaw").unwrap().unwrap();
            assert_eq!(
                hold.contains("provider-declared browser challenge"),
                challenge
            );
            assert!(!hold.contains("session expired"));
            assert_eq!(
                ctx.store.round(&ctx.round_id).unwrap().status,
                RoundStatus::Blocked
            );
        }
    }
    #[test]
    fn old_wire_response_json_retains_identical_bytes_and_hash() {
        let legacy = r#"{"status":200,"headers":{},"body":"old-response"}"#;
        let response: WireResponse = serde_json::from_str(legacy).unwrap();
        assert!(response.set_cookies.is_empty());
        let serialized = serde_json::to_string(&response).unwrap();
        assert_eq!(serialized, legacy);
        assert_eq!(
            crate::model::sha256(serialized.as_bytes()),
            crate::model::sha256(legacy.as_bytes())
        );
    }
    #[tokio::test]
    async fn explicit_relay_uses_connect_without_consuming_tunnel_bytes() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let relay = Url::parse(&format!("http://{}", listener.local_addr().unwrap())).unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let request = String::from_utf8(read_headers(&mut stream).await).unwrap();
            assert!(request.starts_with("CONNECT dyndemo.endorphina.network:443 HTTP/1.1\r\n"));
            stream
                .write_all(b"HTTP/1.1 200 Connection established\r\n\r\nhello")
                .await
                .unwrap();
        });
        let mut stream = connect_tunnel(
            &relay,
            &Url::parse("wss://dyndemo.endorphina.network/organic/websocket/endpoint/1").unwrap(),
        )
        .await
        .unwrap();
        let mut bytes = [0u8; 5];
        stream.read_exact(&mut bytes).await.unwrap();
        assert_eq!(&bytes, b"hello");
        server.await.unwrap();
    }
}
