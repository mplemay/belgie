use std::path::PathBuf;
use std::time::Duration;

use belgie_pool::{Pool, PoolError, PoolOptions};
use serde_json::json;

fn options() -> PoolOptions {
    let mut options = PoolOptions::new(PathBuf::from(env!("CARGO_BIN_EXE_belgie-runtime-worker")));
    options.min_workers = 1;
    options.max_workers = 2;
    options.checkout_timeout = Duration::from_millis(200);
    options.run_timeout = Duration::from_secs(2);
    options
}

#[tokio::test]
async fn prewarms_reuses_and_resets_workers() {
    let pool = Pool::create(options()).await.expect("pool should start");
    assert_eq!(pool.idle_worker_count().await, 1);

    let mut first = pool
        .bind("let calls = 0; export default () => ++calls;".to_string())
        .await
        .expect("first script should bind");
    assert_eq!(
        first.run(Vec::new()).await.expect("run should work"),
        json!(1)
    );
    assert_eq!(
        first.run(Vec::new()).await.expect("run should work"),
        json!(2)
    );
    first.close().await;

    let mut second = pool
        .bind("let calls = 40; export default () => ++calls;".to_string())
        .await
        .expect("second script should bind");
    assert_eq!(
        second.run(Vec::new()).await.expect("run should work"),
        json!(41)
    );
    second.close().await;
    assert_eq!(pool.total_worker_count().await, 1);
    pool.close().await;
}

#[tokio::test]
async fn enforces_the_pool_cap_and_checkout_timeout() {
    let mut pool_options = options();
    pool_options.max_workers = 1;
    pool_options.checkout_timeout = Duration::from_millis(50);
    let pool = Pool::create(pool_options).await.expect("pool should start");
    let mut first = pool
        .bind("export default () => 1;".to_string())
        .await
        .expect("first script should bind");

    let error = match pool.bind("export default () => 2;".to_string()).await {
        Ok(_) => panic!("second checkout should time out"),
        Err(error) => error,
    };
    assert!(matches!(error, PoolError::CheckoutTimeout));

    first.close().await;
    pool.close().await;
}

#[tokio::test]
async fn replaces_a_worker_after_a_run_timeout() {
    let mut pool_options = options();
    pool_options.max_workers = 1;
    pool_options.run_timeout = Duration::from_millis(100);
    let pool = Pool::create(pool_options).await.expect("pool should start");
    let mut stuck = pool
        .bind("export default () => { while (true) {} };".to_string())
        .await
        .expect("infinite script should bind");

    let error = stuck
        .run(Vec::new())
        .await
        .expect_err("infinite script should time out");
    assert!(matches!(error, PoolError::RunTimeout));
    assert!(stuck.is_closed());

    let mut healthy = pool
        .bind("export default (value: number) => value * 2;".to_string())
        .await
        .expect("replacement worker should bind");
    assert_eq!(
        healthy
            .run(vec![json!(21)])
            .await
            .expect("replacement should run"),
        json!(42),
    );
    healthy.close().await;
    pool.close().await;
}

#[tokio::test]
async fn recycles_workers_after_the_configured_checkout_count() {
    let mut pool_options = options();
    pool_options.max_workers = 1;
    pool_options.recycle_after = 1;
    let pool = Pool::create(pool_options).await.expect("pool should start");
    let mut lease = pool
        .bind("export default () => true;".to_string())
        .await
        .expect("script should bind");
    lease.close().await;

    assert_eq!(pool.total_worker_count().await, 1);
    assert_eq!(pool.idle_worker_count().await, 1);
    pool.close().await;
}
