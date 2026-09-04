mod index;
mod model;
mod reconstruct;
mod search;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::index::TransitIndex;
use crate::model::{Endpoint, Leg, Limits, Preference};

type LegOutput = (u32, u32, u32, u32, u32, u32, Vec<u32>);
type PairOutput = (u32, u32, u32, u32, Vec<LegOutput>);
type DiagnosticsOutput = (u64, usize, u64, u32, String, u64);

#[pyclass(module = "_transit_search_core")]
struct TransitSearchIndex {
    inner: TransitIndex,
}

#[pymethods]
impl TransitSearchIndex {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        stop_count: usize,
        route_count: usize,
        service_count: usize,
        trip_route_indices: Vec<u32>,
        trip_service_indices: Vec<u32>,
        trip_offsets: Vec<u32>,
        trip_stop_indices: Vec<u32>,
        arrival_minutes: Vec<i32>,
        departure_minutes: Vec<i32>,
    ) -> PyResult<Self> {
        let inner = TransitIndex::new(
            stop_count,
            route_count,
            service_count,
            trip_route_indices,
            trip_service_indices,
            trip_offsets,
            trip_stop_indices,
            arrival_minutes,
            departure_minutes,
        )
        .map_err(PyValueError::new_err)?;
        Ok(Self { inner })
    }

    #[allow(clippy::too_many_arguments)]
    fn search(
        &self,
        py: Python<'_>,
        active_services: Vec<bool>,
        departure_minute: u32,
        origins: Vec<(u32, u32)>,
        destinations: Vec<(u32, u32)>,
        preference: &str,
        max_rides: u8,
        max_visited_states: u64,
        max_queue_size: usize,
        max_generated_labels: u64,
        time_limit_seconds: f64,
    ) -> PyResult<(Vec<PairOutput>, DiagnosticsOutput)> {
        let preference = Preference::parse(preference).map_err(PyValueError::new_err)?;
        let origins = origins
            .into_iter()
            .map(|(stop_index, walk_minutes)| Endpoint {
                stop_index,
                walk_minutes,
            })
            .collect::<Vec<_>>();
        let destinations = destinations
            .into_iter()
            .map(|(stop_index, walk_minutes)| Endpoint {
                stop_index,
                walk_minutes,
            })
            .collect::<Vec<_>>();
        let limits = Limits {
            max_visited_states,
            max_queue_size,
            max_generated_labels,
            time_limit_seconds,
        };
        let result = py
            .detach(|| {
                search::search(
                    &self.inner,
                    &active_services,
                    departure_minute,
                    &origins,
                    &destinations,
                    preference,
                    max_rides,
                    limits,
                )
            })
            .map_err(PyValueError::new_err)?;

        let pairs = result
            .pairs
            .into_iter()
            .map(|pair| {
                (
                    pair.origin_index,
                    pair.destination_index,
                    pair.itinerary.departure_minute,
                    pair.itinerary.arrival_minute,
                    pair.itinerary.legs.into_iter().map(leg_output).collect(),
                )
            })
            .collect();
        let diagnostics = result.diagnostics;
        Ok((
            pairs,
            (
                diagnostics.visited_states,
                diagnostics.queue_peak,
                diagnostics.generated_labels,
                diagnostics.origin_searches,
                diagnostics.termination_reason,
                diagnostics.elapsed_nanoseconds,
            ),
        ))
    }
}

fn leg_output(leg: Leg) -> LegOutput {
    (
        leg.trip_index,
        leg.route_index,
        leg.from_stop_index,
        leg.to_stop_index,
        leg.departure_minute,
        leg.arrival_minute,
        leg.stop_indices,
    )
}

#[pymodule]
fn _transit_search_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<TransitSearchIndex>()?;
    Ok(())
}
