use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::time::Instant;

use crate::index::TransitIndex;
use crate::model::{
    Diagnostics, Endpoint, Itinerary, Leg, Limits, PairResult, PathKey, Preference, QueueEntry,
    SearchResult,
};
use crate::reconstruct::reconstruct;

#[derive(Default)]
struct Counters {
    visited_states: u64,
    queue_peak: usize,
    generated_labels: u64,
    origin_searches: u32,
}

#[allow(clippy::too_many_arguments)]
pub fn search(
    index: &TransitIndex,
    active_services: &[bool],
    departure_minute: u32,
    origins: &[Endpoint],
    destinations: &[Endpoint],
    preference: Preference,
    max_rides: u8,
    limits: Limits,
) -> Result<SearchResult, String> {
    if active_services.len() != index.service_count {
        return Err("active service mask has the wrong length".to_string());
    }
    if origins.is_empty() || destinations.is_empty() {
        return Err("origins and destinations must not be empty".to_string());
    }
    if max_rides == 0 {
        return Err("max_rides must be >= 1".to_string());
    }
    if !limits.time_limit_seconds.is_finite() || limits.time_limit_seconds <= 0.0 {
        return Err("time_limit_seconds must be finite and > 0".to_string());
    }
    for endpoint in origins.iter().chain(destinations) {
        if endpoint.stop_index as usize >= index.stop_count {
            return Err("endpoint has an invalid stop index".to_string());
        }
    }

    let started = Instant::now();
    let mut counters = Counters::default();
    let mut pairs = Vec::new();
    let mut limit_reason = None;

    for (origin_index, origin) in origins.iter().enumerate() {
        if let Some(reason) = check_limits(&counters, 0, started, limits) {
            limit_reason = Some(reason);
            break;
        }
        counters.origin_searches += 1;
        let origin_departure = match departure_minute.checked_add(origin.walk_minutes) {
            Some(value) => value,
            None => return Err("departure minute overflow".to_string()),
        };
        match search_origin(
            index,
            active_services,
            origin.stop_index,
            origin_departure,
            destinations,
            preference,
            max_rides,
            limits,
            started,
            &mut counters,
        ) {
            Ok(found) => {
                for (destination_index, itinerary) in found.into_iter().enumerate() {
                    if let Some(itinerary) = itinerary {
                        pairs.push(PairResult {
                            origin_index: origin_index as u32,
                            destination_index: destination_index as u32,
                            itinerary,
                        });
                    }
                }
            }
            Err(reason) => {
                limit_reason = Some(reason);
                break;
            }
        }
    }

    let termination_reason = match limit_reason {
        Some(reason) => format!("limit:{reason}"),
        None if pairs.is_empty() => "exhausted".to_string(),
        None => "completed".to_string(),
    };
    let elapsed_nanoseconds = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
    Ok(SearchResult {
        pairs,
        diagnostics: Diagnostics {
            visited_states: counters.visited_states,
            queue_peak: counters.queue_peak,
            generated_labels: counters.generated_labels,
            origin_searches: counters.origin_searches,
            termination_reason,
            elapsed_nanoseconds,
        },
    })
}

#[allow(clippy::too_many_arguments)]
fn search_origin(
    index: &TransitIndex,
    active_services: &[bool],
    origin_stop_index: u32,
    departure_minute: u32,
    destinations: &[Endpoint],
    preference: Preference,
    max_rides: u8,
    limits: Limits,
    started: Instant,
    counters: &mut Counters,
) -> Result<Vec<Option<crate::model::Itinerary>>, String> {
    let mut found = vec![None; destinations.len()];
    let mut remaining = destinations.len();

    for (destination_index, destination) in destinations.iter().enumerate() {
        if destination.stop_index == origin_stop_index {
            found[destination_index] = Some(Itinerary {
                departure_minute,
                arrival_minute: departure_minute,
                legs: Vec::new(),
            });
            remaining -= 1;
        }
    }
    // Preserve zero-ride results, but do not explore or allocate search states
    // when the service calendar has no active services (as in the Python core).
    if remaining == 0 || !active_services.iter().any(|active| *active) {
        return Ok(found);
    }

    let state_width = max_rides as usize + 1;
    let state_count = index
        .stop_count
        .checked_mul(state_width)
        .ok_or_else(|| "search state size overflow".to_string())?;
    let mut best_labels: Vec<Option<(u32, PathKey)>> = vec![None; state_count];
    let mut predecessor: Vec<Option<(usize, Leg)>> = vec![None; state_count];
    let start_state = state_index(origin_stop_index, 0, state_width);
    best_labels[start_state] = Some((departure_minute, Vec::new()));
    let mut queue = BinaryHeap::new();
    let mut serial = 0_u64;
    queue.push(Reverse(queue_entry(
        preference,
        departure_minute,
        0,
        Vec::new(),
        serial,
        origin_stop_index,
    )));
    counters.queue_peak = counters.queue_peak.max(queue.len());

    while let Some(Reverse(entry)) = queue.pop() {
        let current_state = state_index(entry.stop_index, entry.rides, state_width);
        let Some((current_time, current_path_key)) = &best_labels[current_state] else {
            continue;
        };
        if entry.primary != priority(preference, *current_time, entry.rides).0
            || entry.secondary != priority(preference, *current_time, entry.rides).1
            || entry.path_key != *current_path_key
        {
            continue;
        }
        let current_time = *current_time;
        let current_path_key = current_path_key.clone();

        counters.visited_states += 1;
        if counters.visited_states > limits.max_visited_states || counters.visited_states % 256 == 0
        {
            if let Some(reason) = check_limits(counters, queue.len(), started, limits) {
                return Err(reason);
            }
        }

        for (destination_index, destination) in destinations.iter().enumerate() {
            if destination.stop_index == entry.stop_index && found[destination_index].is_none() {
                found[destination_index] = Some(reconstruct(
                    &predecessor,
                    current_state,
                    departure_minute,
                    current_time,
                ));
                remaining -= 1;
            }
        }
        if remaining == 0 {
            break;
        }
        if entry.rides >= max_rides {
            continue;
        }

        let departures = &index.departures_by_stop[entry.stop_index as usize];
        let first = departures.partition_point(|departure| departure.minute < current_time);
        for departure in &departures[first..] {
            let trip_index = departure.trip_index as usize;
            let service_index = index.trip_service_indices[trip_index] as usize;
            if !active_services[service_index] {
                continue;
            }
            let rows = &index.trip_rows[trip_index];
            let origin_row = departure.row_index as usize;
            if origin_row + 1 >= rows.len() {
                continue;
            }
            let next_rides = entry.rides + 1;
            let mut traversed = vec![entry.stop_index];
            for row in &rows[origin_row + 1..] {
                traversed.push(row.stop_index);
                let Some(arrival_minute) = row.arrival_minute else {
                    continue;
                };
                let next_state = state_index(row.stop_index, next_rides, state_width);
                let leg = Leg {
                    trip_index: departure.trip_index,
                    route_index: index.trip_route_indices[trip_index],
                    from_stop_index: entry.stop_index,
                    to_stop_index: row.stop_index,
                    departure_minute: departure.minute,
                    arrival_minute,
                    stop_indices: traversed.clone(),
                };
                let mut next_path_key = current_path_key.clone();
                next_path_key.push(leg.clone());
                let next_label = (arrival_minute, next_path_key.clone());
                if best_labels[next_state]
                    .as_ref()
                    .is_some_and(|prior| prior <= &next_label)
                {
                    continue;
                }
                best_labels[next_state] = Some(next_label);
                predecessor[next_state] = Some((current_state, leg));
                serial += 1;
                counters.generated_labels += 1;
                queue.push(Reverse(queue_entry(
                    preference,
                    arrival_minute,
                    next_rides,
                    next_path_key,
                    serial,
                    row.stop_index,
                )));
                counters.queue_peak = counters.queue_peak.max(queue.len());
                if queue.len() > limits.max_queue_size
                    || counters.generated_labels > limits.max_generated_labels
                    || counters.generated_labels % 256 == 0
                {
                    if let Some(reason) = check_limits(counters, queue.len(), started, limits) {
                        return Err(reason);
                    }
                }
            }
        }
    }
    Ok(found)
}

fn state_index(stop_index: u32, rides: u8, width: usize) -> usize {
    stop_index as usize * width + rides as usize
}

fn priority(preference: Preference, minute: u32, rides: u8) -> (u32, u32) {
    match preference {
        Preference::Fastest => (minute, rides as u32),
        Preference::FewestTransfers => (rides as u32, minute),
    }
}

fn queue_entry(
    preference: Preference,
    minute: u32,
    rides: u8,
    path_key: PathKey,
    serial: u64,
    stop_index: u32,
) -> QueueEntry {
    let (primary, secondary) = priority(preference, minute, rides);
    QueueEntry {
        primary,
        secondary,
        path_key,
        serial,
        stop_index,
        rides,
    }
}

fn check_limits(
    counters: &Counters,
    queue_size: usize,
    started: Instant,
    limits: Limits,
) -> Option<String> {
    if started.elapsed().as_secs_f64() > limits.time_limit_seconds {
        Some("time_limit_seconds".to_string())
    } else if counters.visited_states > limits.max_visited_states {
        Some("max_visited_states".to_string())
    } else if queue_size > limits.max_queue_size {
        Some("max_queue_size".to_string())
    } else if counters.generated_labels > limits.max_generated_labels {
        Some("max_generated_labels".to_string())
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::index::TransitIndex;

    fn tiny_index() -> TransitIndex {
        TransitIndex::new(
            3,
            2,
            1,
            vec![0, 1],
            vec![0, 0],
            vec![0, 2, 4],
            vec![0, 1, 1, 2],
            vec![600, 610, 612, 620],
            vec![600, 610, 612, 620],
        )
        .unwrap()
    }

    #[test]
    fn finds_a_transfer_for_multiple_destinations() {
        let result = search(
            &tiny_index(),
            &[true],
            595,
            &[Endpoint {
                stop_index: 0,
                walk_minutes: 0,
            }],
            &[
                Endpoint {
                    stop_index: 1,
                    walk_minutes: 0,
                },
                Endpoint {
                    stop_index: 2,
                    walk_minutes: 0,
                },
            ],
            Preference::Fastest,
            6,
            Limits {
                max_visited_states: 100,
                max_queue_size: 100,
                max_generated_labels: 100,
                time_limit_seconds: 1.0,
            },
        )
        .unwrap();

        assert_eq!(result.pairs.len(), 2);
        assert_eq!(result.pairs[0].itinerary.arrival_minute, 610);
        assert_eq!(result.pairs[1].itinerary.arrival_minute, 620);
        assert_eq!(result.pairs[1].itinerary.legs.len(), 2);
        assert_eq!(result.diagnostics.termination_reason, "completed");
    }

    #[test]
    fn inactive_services_preserve_zero_ride_pairs_without_exploring() {
        for preference in [Preference::Fastest, Preference::FewestTransfers] {
            let result = search(
                &tiny_index(),
                &[false],
                595,
                &[
                    Endpoint {
                        stop_index: 0,
                        walk_minutes: 2,
                    },
                    Endpoint {
                        stop_index: 1,
                        walk_minutes: 0,
                    },
                ],
                &[
                    Endpoint {
                        stop_index: 0,
                        walk_minutes: 3,
                    },
                    Endpoint {
                        stop_index: 2,
                        walk_minutes: 0,
                    },
                ],
                preference,
                6,
                Limits {
                    max_visited_states: 1,
                    max_queue_size: 1,
                    max_generated_labels: 1,
                    time_limit_seconds: 1.0,
                },
            )
            .unwrap();

            assert_eq!(result.pairs.len(), 1);
            assert_eq!(result.pairs[0].origin_index, 0);
            assert_eq!(result.pairs[0].destination_index, 0);
            assert_eq!(result.pairs[0].itinerary.departure_minute, 597);
            assert_eq!(result.pairs[0].itinerary.arrival_minute, 597);
            assert!(result.pairs[0].itinerary.legs.is_empty());
            assert_eq!(result.diagnostics.visited_states, 0);
            assert_eq!(result.diagnostics.queue_peak, 0);
            assert_eq!(result.diagnostics.generated_labels, 0);
            assert_eq!(result.diagnostics.origin_searches, 2);
            assert_eq!(result.diagnostics.termination_reason, "completed");
        }
    }
}
