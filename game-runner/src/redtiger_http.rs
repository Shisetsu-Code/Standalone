use crate::model::{WireRequest, WireResponse};
use anyhow::{Context, Result, ensure};
use flate2::read::GzDecoder;
use serde_json::json;
use std::{
    fs::{self, OpenOptions},
    io::{self, Read},
    path::{Component, Path},
    process::Stdio,
    time::Duration,
};
use tempfile::TempDir;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
};

const BUNDLE: &[u8] = include_bytes!(env!("REDTIGER_HTTP_BUNDLE"));
const MAX_RESPONSE: u64 = 96 * 1024 * 1024;

pub(crate) struct DirectHttp {
    child: Child,
    request: ChildStdin,
    reply: BufReader<ChildStdout>,
    _files: TempDir,
}

fn number(reader: &mut impl Read) -> Result<u32> {
    let mut bytes = [0; 4];
    reader.read_exact(&mut bytes)?;
    Ok(u32::from_le_bytes(bytes))
}

fn unpack(root: &Path) -> Result<()> {
    let mut archive = GzDecoder::new(BUNDLE);
    loop {
        let name_len = number(&mut archive)? as usize;
        if name_len == 0 {
            ensure!(archive.read(&mut [0])? == 0, "trailing HTTP bundle data");
            return Ok(());
        }
        let size = u64::from(number(&mut archive)?);
        ensure!(
            name_len < 260 && size <= 64 * 1024 * 1024,
            "invalid HTTP bundle entry"
        );
        let mut bytes = vec![0; name_len];
        archive.read_exact(&mut bytes)?;
        let name = std::str::from_utf8(&bytes)?;
        ensure!(
            !name.contains(':')
                && !name.contains('\\')
                && Path::new(name)
                    .components()
                    .all(|part| matches!(part, Component::Normal(_))),
            "invalid HTTP bundle path"
        );
        let path = root.join(name);
        fs::create_dir_all(path.parent().context("HTTP bundle parent absent")?)?;
        let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
        ensure!(
            io::copy(&mut (&mut archive).take(size), &mut file)? == size,
            "short HTTP bundle entry"
        );
    }
}

impl DirectHttp {
    pub(crate) fn new(root: &Path) -> Result<Self> {
        let files = tempfile::Builder::new()
            .prefix("redtiger-http-")
            .tempdir_in(root)?;
        unpack(files.path())?;
        let mut child = Command::new(files.path().join("python.exe"))
            .arg("-I")
            .arg("-B")
            .arg(files.path().join("redtiger_http.py"))
            .current_dir(files.path())
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .env("TEMP", files.path())
            .env("TMP", files.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .spawn()
            .context("start embedded Red Tiger HTTP runtime")?;
        let request = child.stdin.take().context("embedded HTTP input absent")?;
        let reply = BufReader::new(child.stdout.take().context("embedded HTTP output absent")?);
        Ok(Self {
            child,
            request,
            reply,
            _files: files,
        })
    }

    pub(crate) async fn close(self) {
        let Self {
            mut child,
            request,
            reply,
            _files: files,
        } = self;
        drop(request);
        drop(reply);
        if tokio::time::timeout(Duration::from_secs(2), child.wait())
            .await
            .is_err()
        {
            let _ = child.kill().await;
        }
        drop(child);
        drop(files);
    }

    pub(crate) async fn exchange(
        &mut self,
        request: &WireRequest,
        deadline: Duration,
    ) -> Result<WireResponse> {
        let mut bytes = serde_json::to_vec(&json!({
            "method": request.method, "url": request.url, "headers": request.headers,
            "body": request.body, "timeout": deadline.as_secs()
        }))?;
        bytes.push(b'\n');
        self.request.write_all(&bytes).await?;
        self.request.flush().await?;
        let mut reply = Vec::new();
        let size = (&mut self.reply)
            .take(MAX_RESPONSE + 1)
            .read_until(b'\n', &mut reply)
            .await?;
        ensure!(
            size != 0 && size as u64 <= MAX_RESPONSE && reply.last() == Some(&b'\n'),
            "embedded HTTP response missing or too large"
        );
        let data: serde_json::Value = serde_json::from_slice(&reply)?;
        if let Some(error) = data["error"].as_str() {
            anyhow::bail!("embedded HTTP transport error: {error}");
        }
        Ok(serde_json::from_value(data)?)
    }
}
